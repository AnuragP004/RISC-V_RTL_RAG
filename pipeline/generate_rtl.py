import os
from pathlib import Path
import google.generativeai as genai
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

# 1. Setup Environment and API Keys
load_dotenv(Path(__file__).parent / ".env")
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

# 2. Connect to your existing ChromaDB
chroma_client = chromadb.PersistentClient(path="data/chroma_db")

# Setup Gemini embedding function, same as embed_and_store.py
gemini_ef = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
    api_key=api_key,
    task_type="RETRIEVAL_DOCUMENT"
)

collection = chroma_client.get_collection(
    name="verilog_rtl",
    embedding_function=gemini_ef
)

# Initialize the Gemini Generation Model (using Gemini 2.5 Pro for complex coding)
model = genai.GenerativeModel('gemini-2.5-pro')

def retrieve_context(query, k=3):
    """Retrieves the top-k Verilog chunks matching the query."""
    print(f"[*] Retrieving context for: {query}")
    results = collection.query(
        query_texts=[query],
        n_results=k
    )
    
    # Flatten the retrieved documents into a single string
    context_str = "\n\n--- RETRIEVED VERILOG CONTEXT ---\n\n"
    if results['documents'] and results['documents'][0]:
        for idx, doc in enumerate(results['documents'][0]):
            context_str += f"// Chunk {idx+1}\n{doc}\n\n"
    return context_str

def generate_component(component_name, interface_definition, specific_warnings="", filename=None):
    """Orchestrates RAG to generate a specific RISC-V component."""
    
    # 1. Retrieve Context
    query = f"Verilog implementation of RV32I {component_name}"
    context = retrieve_context(query)
    
    # 2. Build the System Prompt (incorporating Claude's and the PDF's rules)
    prompt = f"""
    You are an expert hardware RTL engineer. Your task is to generate synthesizable Verilog code for a 32-bit RISC-V (RV32I) processor component.

    [STRICT HARDWARE RULES - DO NOT VIOLATE]
    1. Use non-blocking assignments (<=) in ALL clocked sequential blocks (always @(posedge clk)).
    2. Never use blocking assignments (=) in clocked blocks.
    3. Use always @(*) or always_comb for ALL combinational logic. Do not write manual sensitivity lists.
    4. Provide default assignments at the top of every combinational block to prevent unintended latch inference.
    5. Variables assigned inside always blocks MUST be declared as 'reg' (or output reg). Do not assign to 'wire' inside procedural blocks.
    
    [TASK]
    Generate the {component_name} module.
    
    [INTERFACE DEFINITION]
    {interface_definition}
    
    [KNOWN FAILURE MODES TO AVOID]
    {specific_warnings}

    [REFERENCE CONTEXT]
    The following are verified Verilog snippets from reference RISC-V cores. Use them to guide your structural design, but adapt them to the Interface Definition provided above.
    {context}

    OUTPUT STRICTLY VALID VERILOG CODE. Do not include markdown formatting like ```verilog. Do not include conversational explanations. Just the code.
    """
    
    print(f"[*] Generating {component_name} via Gemini...")
    response = model.generate_content(prompt)
    
    # Clean up the output in case the LLM still outputs markdown fences
    clean_code = response.text.replace("```verilog\n", "").replace("```", "").strip()
    
    # 3. Save to File
    if not filename:
        safe_name = component_name.lower().replace(' ', '_').replace('/', '_')
        filename = f"{safe_name}.v"
        
    with open(filename, "w") as f:
        f.write(clean_code)
    
    print(f"[+] Successfully saved to {filename}\n")
    return clean_code

# --- EXECUTION ---
if __name__ == "__main__":
    # Let's start with the easiest component to test the pipeline: The ALU
    core_interface = """
    module rv32i_core (
        input  clk,
        input  reset,
        input  [31:0] instr_mem_data,
        output [31:0] instr_mem_addr
    );
    """
    
    core_warnings = """
    [CRITICAL ERROR RECOVERY - PORT MISMATCHES]
    Your previous attempt failed synthesis because you hallucinated the port names of the sub-modules. You MUST instantiate the modules using the EXACT port names defined below. Do not invent names like `pc_in`, `in1`, or `rs1_addr`.

    1. program_counter ports: `clk`, `reset`, `branch_target`, `pc_sel`, `pc`
    2. decoder ports: `instr`, `opcode`, `rd`, `funct3`, `rs1`, `rs2`, `funct7`, `imm`
    3. register_file ports: `clk`, `rs1`, `rs2`, `rd`, `write_data`, `reg_write`, `rs1_data`, `rs2_data`
    4. branch_unit ports: `rs1_data`, `rs2_data`, `funct3`, `branch_taken`
    5. alu ports: `a`, `b`, `alu_control`, `result`, `zero`

    [ROUTING INSTRUCTIONS]
    - Connect `instr_mem_addr` to `pc`.
    - Connect `instr_mem_data` to `instr`.
    - Declare all intermediate wires necessary to connect the data paths (e.g., routing `rs1` from the decoder to `rs1` on the register file).
    - Write a small combinational block to decode `alu_control` and `reg_write` from the `opcode`.
    """
    
    generate_component("RV32I Core", core_interface, core_warnings)