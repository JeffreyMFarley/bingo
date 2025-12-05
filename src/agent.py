import json

from langfuse import get_client
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from src.retriever_llama import RetrieverLlama

# Define the tools for OpenAI
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "chunk_retrieve",
            "description": "Retrieve relevant text chunks from documents. Use this for specific factual questions that need precise information from small sections of documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant chunks"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_retrieve",
            "description": "Retrieve entire files based on content relevance. Use this when you need broader context or when the answer might span multiple sections of a document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant files"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


def execute_tool(tool_name, arguments, retriever: RetrieverLlama):
    """Execute the requested tool and return results."""
    query = arguments.get("query", "")
    
    if tool_name == "chunk_retrieve":
        retriever.retrieval_mode = "chunks"
        retrieved, context = retriever.query(query)
        return {"retrieved": retrieved, "context": context}
    elif tool_name == "file_retrieve":
        retriever.retrieval_mode = "files"
        retrieved, context = retriever.query(query)
        return {"retrieved": retrieved, "context": context}
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def query_index_and_generate(query, retriever: RetrieverLlama, openai_model, openai_key):
    if OpenAI is None:
        raise RuntimeError("openai package is required. Install from requirements.txt")
    client = OpenAI(api_key=openai_key)

    try:
        langfuse_cli = get_client()
    except Exception:
        print("Langfuse client initialization failed. Make sure LANGFUSE keys are set in .env.")
        langfuse_cli = None

    system = "You are an assistant that answers questions using retrieved documents. First decide which retrieval method to use, then answer based on the context. If the answer is not in the context, say you don't know and be concise."
    
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": query}
    ]

    retrieved_docs = []
    final_context = ""

    with langfuse_cli.start_as_current_observation(
        as_type="generation",
        name="call-llm",
        model=openai_model,
        input={"query": query, "system": system},
        model_parameters={"temperature": 0.0}
    ) as span:
        try:
            resp = client.chat.completions.create(
                model=openai_model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.0
            )

            message = resp.choices[0].message
            
            # Handle tool calls
            if message.tool_calls:
                messages.append(message)
                
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    print(f"--- Tool Called: {tool_name} ---")
                    print(f"Arguments: {arguments}")
                    
                    # Execute tool
                    result = execute_tool(tool_name, arguments, retriever)
                    retrieved_docs = result.get("retrieved", [])
                    final_context = result.get("context", "")
                    
                    print("--- Retrieved docs ---")
                    for r in retrieved_docs:
                        print(r)
                    
                    # Add tool response to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps({"context": final_context})
                    })
                
                # Get final response with tool results
                resp = client.chat.completions.create(
                    model=openai_model,
                    messages=messages,
                    max_tokens=512,
                    temperature=0.0
                )
            
            final_response = resp.choices[0].message.content
            span.update(output={"response": final_response, "retrieved_docs": retrieved_docs})
            
        except Exception as e:
            span.update(error={"message": str(e)})
            raise
        finally:
            langfuse_cli.flush()

    return final_response.strip(), retrieved_docs