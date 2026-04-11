# pipeline/chunk_verilog.py
import re
import os
import json
from pathlib import Path
from typing import List, Dict

def chunk_verilog_file(filepath: str) -> List[Dict]:
    """
    Rule-based AST-style chunker for Verilog files.
    
    Strategy:
    - Module boundaries define top-level chunks
    - always blocks are ATOMIC — never split
    - wire/reg declarations are bundled with the module header
    - Each chunk carries module name as metadata
    """
    
    with open(filepath, 'r', errors='replace') as f:
        content = f.read()
    
    filename = Path(filepath).name
    chunks = []
    
    # Split into modules first
    modules = split_into_modules(content)
    
    for module_name, module_body in modules:
        # Extract port + parameter declarations (global context)
        module_header = extract_module_header(module_body)
        wire_decls = extract_declarations(module_body)
        
        # Extract always blocks (atomic units)
        always_blocks = extract_always_blocks(module_body)
        
        # Extract assign statements (group them)
        assign_groups = extract_assign_groups(module_body)
        
        # Build chunks
        # Chunk 1: Module header + all declarations (always injected as metadata)
        header_chunk = {
            "id": f"{filename}::{module_name}::header",
            "type": "module_header",
            "module_name": module_name,
            "source": filename,
            "content": module_header + "\n\n// Internal declarations:\n" + wire_decls,
            "metadata": {
                "module_name": module_name,
                "chunk_type": "header_declarations",
                "source_file": filename,
            }
        }
        chunks.append(header_chunk)
        
        # Chunks for always blocks
        for i, block in enumerate(always_blocks):
            block_type = infer_block_type(block)
            chunk = {
                "id": f"{filename}::{module_name}::always_{i}",
                "type": "always_block",
                "module_name": module_name,
                "source": filename,
                # Prepend module context so LLM knows the surrounding architecture
                "content": f"// Module: {module_name}\n// File: {filename}\n\n{block}",
                "metadata": {
                    "module_name": module_name,
                    "chunk_type": f"always_block_{block_type}",
                    "source_file": filename,
                    "block_index": i,
                }
            }
            chunks.append(chunk)
        
        # Chunks for assign groups (combinational logic)
        if assign_groups:
            chunk = {
                "id": f"{filename}::{module_name}::assigns",
                "type": "assign_statements",
                "module_name": module_name,
                "source": filename,
                "content": f"// Module: {module_name}\n// Continuous assignments:\n\n" + assign_groups,
                "metadata": {
                    "module_name": module_name,
                    "chunk_type": "continuous_assignments",
                    "source_file": filename,
                }
            }
            chunks.append(chunk)
    
    return chunks


def split_into_modules(content: str) -> List[tuple]:
    """Extract (module_name, module_body) pairs."""
    modules = []
    # Match module declarations
    pattern = r'(module\s+(\w+).*?endmodule)'
    matches = re.findall(pattern, content, re.DOTALL)
    for body, name in matches:
        modules.append((name, body))
    
    # If no modules found (e.g., include files), treat whole file as one chunk
    if not modules:
        modules = [("unknown", content)]
    
    return modules


def extract_module_header(module_body: str) -> str:
    """Extract module declaration up to first always/assign/initial."""
    # Get everything before the first procedural block
    split_pattern = r'(?=\s*always\s*@|\s*assign\s+|\s*initial\s+)'
    parts = re.split(split_pattern, module_body, maxsplit=1)
    return parts[0].strip()


def extract_declarations(module_body: str) -> str:
    """Extract all wire, reg, logic, parameter declarations."""
    decl_pattern = r'^\s*(wire|reg|logic|parameter|localparam|input|output|inout)[^;]+;'
    matches = re.findall(decl_pattern, module_body, re.MULTILINE)
    
    # Re-extract full lines
    lines = []
    for line in module_body.split('\n'):
        stripped = line.strip()
        if re.match(r'^(wire|reg|logic|parameter|localparam)\s+', stripped):
            lines.append(line)
    
    return '\n'.join(lines)


def extract_always_blocks(module_body: str) -> List[str]:
    """
    Extract always blocks as atomic units.
    Uses bracket/begin-end counting to find block boundaries.
    Never splits an always block.
    """
    blocks = []
    lines = module_body.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Detect start of always block
        if re.match(r'\s*always\s*@', line):
            block_lines = [line]
            begin_count = line.count('begin') - line.count('end')
            
            # If single-line always (no begin), grab next statement
            if begin_count == 0 and 'begin' not in line:
                i += 1
                if i < len(lines):
                    block_lines.append(lines[i])
                blocks.append('\n'.join(block_lines))
                i += 1
                continue
            
            # Multi-line: count begin/end to find the boundary
            i += 1
            while i < len(lines) and begin_count > 0:
                l = lines[i]
                begin_count += l.count('begin') - l.count('end')
                # Handle 'endcase' which doesn't pair with 'begin'
                begin_count += l.count('case') - l.count('endcase') - l.count('case')  
                block_lines.append(l)
                i += 1
            
            blocks.append('\n'.join(block_lines))
        else:
            i += 1
    
    return blocks


def extract_assign_groups(module_body: str) -> str:
    """Extract all continuous assign statements."""
    lines = []
    for line in module_body.split('\n'):
        if re.match(r'\s*assign\s+', line):
            lines.append(line)
    return '\n'.join(lines)


def infer_block_type(block: str) -> str:
    """Infer what a block does from its content."""
    block_lower = block.lower()
    if 'posedge clk' in block_lower or 'negedge clk' in block_lower:
        if 'reset' in block_lower or 'rst' in block_lower:
            return 'sequential_with_reset'
        return 'sequential'
    return 'combinational'


def chunk_token_limit(chunk: Dict, max_tokens: int = 600) -> List[Dict]:
    """
    If an always block exceeds max_tokens, split at case boundaries.
    This handles large FSMs like in PicoRV32.
    """
    # Rough token estimate: 1 token ≈ 4 chars
    if len(chunk['content']) / 4 <= max_tokens:
        return [chunk]
    
    content = chunk['content']
    # Split at case state boundaries
    case_pattern = r'(?=\s+[A-Z_]+:\s*begin|\s+\d+\'[bh][\w]+:\s*begin)'
    sub_blocks = re.split(case_pattern, content)
    
    # Extract the always header to prepend to each sub-chunk
    header_match = re.match(r'(always\s*@[^;]+begin)', content, re.DOTALL)
    header = header_match.group(1) if header_match else ''
    
    result = []
    for j, sub in enumerate(sub_blocks):
        if not sub.strip():
            continue
        sub_chunk = chunk.copy()
        sub_chunk['id'] = f"{chunk['id']}::fsm_{j}"
        sub_chunk['content'] = f"{header}\n{sub}\nend  // FSM sub-chunk {j}"
        sub_chunk['metadata'] = {**chunk['metadata'], 'fsm_subchunk': j}
        result.append(sub_chunk)
    
    return result if result else [chunk]


def process_all_verilog(raw_dir: str, output_path: str):
    """Process all .v files in raw_dir and save chunks to JSON."""
    raw_path = Path(raw_dir)
    all_chunks = []
    
    verilog_files = list(raw_path.glob('**/*.v')) + list(raw_path.glob('**/*.sv'))
    print(f"Found {len(verilog_files)} Verilog files")
    
    for vf in verilog_files:
        print(f"  Chunking: {vf.name}")
        try:
            chunks = chunk_verilog_file(str(vf))
            # Apply token limit splitting for large blocks
            final_chunks = []
            for c in chunks:
                final_chunks.extend(chunk_token_limit(c))
            all_chunks.extend(final_chunks)
            print(f"    → {len(final_chunks)} chunks")
        except Exception as e:
            print(f"    ✗ Error: {e}")
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(all_chunks, f, indent=2)
    
    print(f"\nTotal Verilog chunks: {len(all_chunks)}")
    print(f"Saved to: {output_path}")
    return all_chunks


if __name__ == "__main__":
    process_all_verilog("corpus/raw", "corpus/chunks/verilog_chunks.json")