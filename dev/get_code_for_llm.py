import argparse
from pathlib import Path
from typing import List, Set, Optional, Dict
from datetime import datetime

# File extensions to include
FILE_EXTENSIONS = {'.py', '.json', '.jsx', '.css', '.html'}

# Language mapping for file headers
LANGUAGE_MAP = {
    '.py': 'Python',
    '.json': 'JSON',
    '.jsx': 'JSX/React',
    '.css': 'CSS',
    '.html': 'HTML'
}

def collect_project_files(
    root_dir: str, 
    exclude_folders: Set[str], 
    exclude_patterns: Set[str]
) -> Dict[str, List[Path]]:
    """
    Recursively collect all project files (Python, JSON, JSX, CSS, HTML) in the directory,
    excluding specified folders and patterns.
    Returns a dictionary grouped by file type.
    """
    files_by_type = {ext: [] for ext in FILE_EXTENSIONS}
    root_path = Path(root_dir).resolve()
    
    for ext in FILE_EXTENSIONS:
        pattern = f"*{ext}"
        for path in root_path.rglob(pattern):
            # Check if any part of the path matches excluded folders
            path_parts = path.relative_to(root_path).parts
            if any(part in exclude_folders for part in path_parts):
                continue
                
            # Check if the file matches any exclude patterns
            if any(pattern in str(path) for pattern in exclude_patterns):
                continue
                
            files_by_type[ext].append(path)
    
    # Sort files within each type
    for ext in files_by_type:
        files_by_type[ext].sort()
    
    return files_by_type

def format_file_header(file_path: Path, root_dir: Path) -> str:
    """
    Create a formatted header for each file in the consolidated output.
    """
    relative_path = file_path.relative_to(root_dir)
    file_ext = file_path.suffix
    language = LANGUAGE_MAP.get(file_ext, 'Unknown')
    separator = "=" * 80
    return f"\n{separator}\n# File: {relative_path}\n# Type: {language}\n{separator}\n\n"

def get_comment_syntax(file_ext: str) -> tuple:
    """
    Return the appropriate comment syntax for different file types.
    Returns (single_line_comment, multi_line_start, multi_line_end)
    """
    if file_ext in ['.py']:
        return '#', '"""', '"""'
    elif file_ext in ['.jsx', '.css']:
        return '//', '/*', '*/'
    elif file_ext in ['.html']:
        return None, '<!--', '-->'
    elif file_ext in ['.json']:
        return None, None, None  # JSON doesn't support comments
    return '#', None, None

def consolidate_project(
    root_dir: str,
    output_file: str,
    exclude_folders: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    include_empty_files: bool = False
) -> None:
    """
    Main function to consolidate all project files into a single file.
    """
    # Default exclusions
    default_exclude_folders = {
        "__pycache__", ".git", ".venv", "venv", "env", 
        ".env", "node_modules", ".pytest_cache", ".mypy_cache",
        "dist", "build", ".egg-info", ".tox", ".coverage", "dev",
        ".next", ".cache", "coverage", "tmp", "temp"
    }
    
    default_exclude_patterns = {
        ".pyc", "__pycache__", ".git", ".DS_Store", 
        ".min.js", ".min.css", "package-lock.json", "yarn.lock"
    }
    
    # Merge with user-provided exclusions
    exclude_folders_set = default_exclude_folders
    if exclude_folders:
        exclude_folders_set.update(exclude_folders)
    
    exclude_patterns_set = default_exclude_patterns
    if exclude_patterns:
        exclude_patterns_set.update(exclude_patterns)
    
    # Collect project files
    root_path = Path(root_dir).resolve()
    files_by_type = collect_project_files(root_dir, exclude_folders_set, exclude_patterns_set)
    
    # Count total files
    total_files = sum(len(files) for files in files_by_type.values())
    
    if total_files == 0:
        print(f"No project files found in {root_dir}")
        return
    
    # Write consolidated file
    with open(output_file, 'w', encoding='utf-8') as outfile:
        # Write header
        outfile.write("# Consolidated Project Files\n")
        outfile.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        outfile.write(f"# Source directory: {root_path}\n")
        outfile.write(f"# Total files: {total_files}\n")
        
        # Write file type summary
        outfile.write("\n# File Summary:\n")
        for ext, files in files_by_type.items():
            if files:
                outfile.write(f"#   {LANGUAGE_MAP.get(ext, ext)}: {len(files)} files\n")
        
        outfile.write("# " + "=" * 78 + "\n\n")
        
        # Write table of contents
        outfile.write("# TABLE OF CONTENTS\n")
        outfile.write("# " + "-" * 78 + "\n")
        file_number = 1
        for ext in FILE_EXTENSIONS:
            if files_by_type[ext]:
                outfile.write(f"\n# {LANGUAGE_MAP.get(ext, ext)} Files:\n")
                for file_path in files_by_type[ext]:
                    relative_path = file_path.relative_to(root_path)
                    outfile.write(f"#   {file_number}. {relative_path}\n")
                    file_number += 1
        outfile.write("\n# " + "=" * 78 + "\n\n")
        
        # Write file contents grouped by type
        for ext in FILE_EXTENSIONS:
            files = files_by_type[ext]
            if not files:
                continue
                
            # Section header for file type
            outfile.write(f"\n{'#' * 80}\n")
            outfile.write(f"# {LANGUAGE_MAP.get(ext, ext).upper()} FILES\n")
            outfile.write(f"{'#' * 80}\n")
            
            for file_path in files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                        
                        # Skip empty files unless specified
                        if not include_empty_files and not content.strip():
                            continue
                        
                        # Write file header and content
                        outfile.write(format_file_header(file_path, root_path))
                        outfile.write(content)
                        
                        # Ensure there's a newline at the end of each file
                        if not content.endswith('\n'):
                            outfile.write('\n')
                            
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    outfile.write(f"\n# ERROR reading file: {e}\n\n")
    
    # Print summary
    print(f"\nSuccessfully consolidated {total_files} files into {output_file}")
    print("\nFile breakdown:")
    for ext, files in files_by_type.items():
        if files:
            print(f"  {LANGUAGE_MAP.get(ext, ext)}: {len(files)} files")

def main():
    parser = argparse.ArgumentParser(
        description="Consolidate project files (Python, JSON, JSX, CSS, HTML) into a single file"
    )
    parser.add_argument(
        "root_dir",
        nargs="?",
        default=".",
        help="Root directory of the project (default: current directory)"
    )
    parser.add_argument(
        "-o", "--output",
        default="consolidated_project.txt",
        help="Output file name (default: consolidated_project.txt)"
    )
    parser.add_argument(
        "-e", "--exclude-folders",
        nargs="+",
        help="Additional folders to exclude (e.g., tests docs)"
    )
    parser.add_argument(
        "-p", "--exclude-patterns",
        nargs="+",
        help="Additional patterns to exclude from file paths"
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="Include empty files in the output"
    )
    parser.add_argument(
        "-t", "--types",
        nargs="+",
        choices=['py', 'json', 'jsx', 'css', 'html'],
        help="Specific file types to include (default: all)"
    )
    
    args = parser.parse_args()
    
    # If specific types are requested, update FILE_EXTENSIONS
    if args.types:
        global FILE_EXTENSIONS
        FILE_EXTENSIONS = {f'.{ext}' for ext in args.types}
    
    consolidate_project(
        root_dir=args.root_dir,
        output_file=args.output,
        exclude_folders=args.exclude_folders,
        exclude_patterns=args.exclude_patterns,
        include_empty_files=args.include_empty
    )

if __name__ == "__main__":
    main()
