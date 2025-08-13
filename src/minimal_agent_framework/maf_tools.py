import os
import sys
import requests
import json
import subprocess
import shutil

from .tool import tool
from typing import Any
from ddgs import DDGS
from dotenv import load_dotenv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")
BRAVE_SEARCH_API_WEB_ENDPOINT = os.getenv("BRAVE_SEARCH_API_WEB_ENDPOINT")

if BRAVE_SEARCH_API_KEY is None:
    raise ValueError("BRAVE_SEARCH_API_KEY is not set")
if BRAVE_SEARCH_API_WEB_ENDPOINT is None:
    raise ValueError("BRAVE_SEARCH_API_WEB_ENDPOINT is not set")

BUFFER = 0.05 # 5% buffer
MAX_QUERY_LENGTH = int(400 * (1 - BUFFER))
MAX_QUERY_WORDS = int(50 * (1 - BUFFER))
MAX_RESULTS = 5


@tool
def search(query: str, max_results: int = MAX_RESULTS) -> str:
    """Search the web for a query using DuckDuckGo."""
    
    duckduckgo_results = search_duckduckgo(query, max_results)
    brave_results = search_brave(query, max_results)
    return json.dumps({**duckduckgo_results, **brave_results})


def search_duckduckgo(query: str, max_results: int = MAX_RESULTS) -> dict[Any, Any]:
    """Search the web for a query using DuckDuckGo."""
    try:
        results = DDGS().text(query, max_results=max_results)
        return format_duckduckgo_results(results)
    except Exception as e:
        return {"error": str(e)}

def search_brave(query: str, max_results: int = MAX_RESULTS) -> dict[Any, Any]:
    """Search the web for a query using Brave Search."""
    try:
        # ensure query is no more than 400 characters
        if len(query) > MAX_QUERY_LENGTH:
            query = str(query[:MAX_QUERY_LENGTH - 3] + "...")
        
        # ensure query is no more than 50 words
        if len(query.split()) > MAX_QUERY_WORDS:
            query = str(" ".join(query.split()[:MAX_QUERY_WORDS - 1]) + "...")

        
        assert BRAVE_SEARCH_API_WEB_ENDPOINT is not None
        response = requests.get(BRAVE_SEARCH_API_WEB_ENDPOINT, params={"q": query, "search_lang": "en", "count": str(max_results), "summary": "true"}, 
                                headers={"X-Subscription-Token": BRAVE_SEARCH_API_KEY,
                                         "Accept": "application/json",
                                         "Accept-Encoding": "gzip"})
        return format_brave_results(response.json())
    except Exception as e:
        return {"error": str(e)}

def format_brave_results(result: dict[str, Any]) -> dict[Any, Any]:
    web_results = result["web"]["results"]
    response = {}
    for result in web_results:
        title = result["title"]
        description = result["description"]
        url = result["url"] 
        response[url] = {
            "title": title,
            "description": description,
        }
    return response

def format_duckduckgo_results(results: list[dict[str, Any]]) -> dict[Any, Any]:
    response = {}
    for result in results:
        title = result["title"]
        description = result["body"]
        url = result["href"]
        response[url] = {
            "title": title,
            "description": description,
        }
    return response



### file tools

@tool
def read_file_content(file_path: str) -> dict[str, Any]:
    """Read and return file contents."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return {
            "status": "success",
            "file_path": file_path,
            "content": content,
            "size": len(content)
        }
    except FileNotFoundError:
        return {"status": "error", "message": f"File not found: {file_path}"}
    except Exception as e:
        return {"status": "error", "message": f"Error reading file: {str(e)}"}

@tool
def write_file(file_path: str, content: str) -> dict[str, Any]:
    """Write content to a file (overwrites existing content)."""
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)
        return {
            "status": "success",
            "file_path": file_path,
            "message": "File written successfully",
            "size": len(content)
        }
    except Exception as e:
        return {"status": "error", "message": f"Error writing file: {str(e)}"}

@tool
def append_to_file(file_path: str, content: str) -> dict[str, Any]:
    """Append content to the end of a file."""
    try:
        with open(file_path, 'a', encoding='utf-8') as file:
            file.write(content)
        return {
            "status": "success",
            "file_path": file_path,
            "message": "Content appended successfully"
        }
    except Exception as e:
        return {"status": "error", "message": f"Error appending to file: {str(e)}"}

@tool
def replace_in_file(file_path: str, search_pattern: str, replacement: str) -> dict[str, Any]:
    """Replace all occurrences of a pattern in a file."""    
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Count replacements
        count = content.count(search_pattern)
        
        # Replace content
        new_content = content.replace(search_pattern, replacement)
        
        # Write back
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(new_content)
        
        return {
            "status": "success",
            "file_path": file_path,
            "replacements_made": count,
            "message": f"Replaced {count} occurrences"
        }
    except Exception as e:
        return {"status": "error", "message": f"Error replacing content: {str(e)}"}

@tool
def delete_lines_from_file(file_path: str, line_numbers: list[int]) -> dict[str, Any]:
    """Delete specific lines from a file by line numbers (1-indexed)."""    
    try:
        # Read all lines
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        # Convert to 0-indexed and sort in reverse order
        line_numbers_0indexed = sorted([ln - 1 for ln in line_numbers], reverse=True)
        
        # Remove lines
        removed_count = 0
        for line_num in line_numbers_0indexed:
            if 0 <= line_num < len(lines):
                del lines[line_num]
                removed_count += 1
        
        # Write back
        with open(file_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)
        
        return {
            "status": "success",
            "file_path": file_path,
            "lines_removed": removed_count,
            "total_lines": len(lines)
        }
    except Exception as e:
        return {"status": "error", "message": f"Error deleting lines: {str(e)}"}

@tool
def insert_at_line(file_path: str, line_number: int, content: str) -> dict[str, Any]:
    """Insert content at a specific line number (1-indexed)."""  
    try:
        # Read all lines
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        # Convert to 0-indexed
        line_index = line_number - 1
        
        # Ensure content ends with newline if needed
        if not content.endswith('\n'):
            content += '\n'
        
        # Insert at the specified position
        if line_index <= 0:
            lines.insert(0, content)
        elif line_index >= len(lines):
            lines.append(content)
        else:
            lines.insert(line_index, content)
        
        # Write back
        with open(file_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)
        
        return {
            "status": "success",
            "file_path": file_path,
            "inserted_at_line": line_number,
            "total_lines": len(lines)
        }
    except Exception as e:
        return {"status": "error", "message": f"Error inserting content: {str(e)}"}

@tool
def create_file_backup(file_path: str) -> dict[str, Any]:
    """Create a backup of a file with timestamp."""
    try:
        if not os.path.exists(file_path):
            return {"status": "error", "message": "File not found"}
        
        # Create backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{file_path}.backup_{timestamp}"
        
        # Copy file
        shutil.copy2(file_path, backup_path)
        
        return {
            "status": "success",
            "message": f"Backup created: {backup_path}"
        }
    except Exception as e:
        return {"status": "error", "message": f"Error creating backup: {str(e)}"}


@tool
def execute_shell_command(command: str) -> dict[str, Any]:
    """Execute shell command with timeout."""
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Command timed out"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
