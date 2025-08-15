import argparse
import os
import fnmatch
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

def _matches_any_pattern(path_str: str, patterns: Set[str]) -> bool:
    """
    Return True if path_str matches any of the patterns.
    Supports both substring and simple glob patterns.
    """
    if not patterns:
        return False
    norm = path_str.replace(os.sep, '/')
    for pat in patterns:
        if not pat:
            continue
        # Glob match if wildcard chars present
        if any(ch in pat for ch in ['*', '?', '[', ']']):
            if fnmatch.fnmatch(norm, pat):
                return True
        # Otherwise substring match
        if pat in norm:
            return True
    return False

def _split_folder_matchers(exclude_folders: Set[str]):
    """
    Split exclude_folders into exact-name matches and glob patterns.
    Matching is case-insensitive on folder names.
    """
    exact: Set[str] = set()
    globs: Set[str] = set()
    for raw in exclude_folders or []:
        name = (raw or '').strip()
        if not name:
            continue
        lower = name.lower().replace(os.sep, '/')
        if any(ch in lower for ch in ['*', '?', '[', ']']):
            globs.add(lower)
        else:
            exact.add(lower)
    return exact, globs

def collect_project_files(
    root_dir: str,
    exclude_folders: Set[str],
    exclude_patterns: Set[str]
) -> Dict[str, List[Path]]:
    """
    Recursively collect all project files (Python, JSON, JSX, CSS, HTML) in the directory,
    excluding specified folders and patterns. Excluded folders are pruned at any depth.
    Returns a dictionary grouped by file type.
    """
    files_by_type = {ext: [] for ext in FILE_EXTENSIONS}
    root_path = Path(root_dir).resolve()

    # Prepare folder matchers
    exclude_exact_names, exclude_glob_names = _split_folder_matchers(exclude_folders)

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=False):
        # Compute relative directory path from root for pattern checks
        rel_dir = Path(dirpath).resolve().relative_to(root_path)
        rel_dir_str = '' if str(rel_dir) == '.' else str(rel_dir)

        # Prune dirnames in-place so we never descend into excluded directories
        pruned = []
        for d in dirnames:
            d_lower = d.lower()
            # Exclude by exact folder name
            if d_lower in exclude_exact_names:
                continue
            # Exclude by folder-name glob (e.g., venv*, .venv*, env*)
            if any(fnmatch.fnmatch(d_lower, pat) for pat in exclude_glob_names):
                continue
            # Exclude by path-based patterns (apply to the relative path of this child dir)
            rel_child_path = str(Path(rel_dir_str, d)) if rel_dir_str else d
            if _matches_any_pattern(rel_child_path, exclude_patterns):
                continue
            pruned.append(d)
        dirnames[:] = pruned  # important: mutate in-place to prune traversal

        # Process files in this directory
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext not in FILE_EXTENSIONS:
                continue

            file_path = Path(dirpath) / fname
            rel_file_path = file_path.relative_to(root_path)
            rel_file_str = str(rel_file_path)

            # Apply path-based patterns to files too
            if _matches_any_pattern(rel_file_str, exclude_patterns):
                continue

            files_by_type[ext].append(file_path)

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
        "__pycache__", ".git", "node_modules",
        # Common virtual environment dirs (support versions/suffixes)
        ".venv", ".venv*", "venv", "venv*", "env", "env*",
        # Other typical build/cache dirs
        ".pytest_cache", ".mypy_cache", "dist", "build", ".egg-info", ".tox",
        "dev", ".next", ".cache", "coverage", "tmp", "temp"
    }

    default_exclude_patterns = {
        ".pyc", "__pycache__", ".git", ".DS_Store",
        ".min.js", ".min.css", "package-lock.json", "yarn.lock"
    }

    # Merge with user-provided exclusions
    exclude_folders_set = set(default_exclude_folders)
    if exclude_folders:
        exclude_folders_set.update(exclude_folders)

    exclude_patterns_set = set(default_exclude_patterns)
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
        help="Additional folders to exclude (supports globs; e.g., tests docs venv* .venv*)"
    )
    parser.add_argument(
        "-p", "--exclude-patterns",
        nargs="+",
        help="Additional patterns to exclude from file paths (supports substrings and globs)"
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
