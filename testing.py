from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("AZURE_API_KEY")
base_url = os.getenv("AZURE_API_ENDPOINT")
client = OpenAI(api_key=api_key, base_url=base_url, default_query={"api-version": "preview"})
model = os.getenv("AZURE_MAIN_MODEL_DEPLOYMENT")

resp = client.responses.create(
    model=str(model),
    tools=[
        {
            "type": "mcp",
            "server_label": "context7",
            "server_url": "https://mcp.context7.com/mcp",
            "require_approval": "never",
        },
    ],
    input="Use the contex7 mcp and tell me what about PydanticAI - the AI Framework",
)

print(resp.output_text)