"""
kb_storage.py

Stores Knowledge Base (.md) files on the backend's own filesystem, in a
folder structure that is created automatically the first time it's needed:

    backend/kb_storage/<project-slug>/<task-slug>/<timestamp>_<filename>.md

This is a plain local backup -- separate from (and independent of) the
XWiki integration in services.py. It has no external dependencies, so it
can be run standalone (see the __main__ block at the bottom) as well as
imported from the Flask app.
"""

import os
import re
import time

# All KB files live under this folder, next to this file, i.e.
# backend/kb_storage/. Created lazily -- see save_kb_file() below.
KB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kb_storage')


def _slugify(value, default='untitled'):
    """Turn an arbitrary string into a safe folder/file name component."""
    value = (value or '').strip().lower()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    value = value.strip('-')[:80]
    return value or default


def save_kb_file(project_name, task_name, filename, content):
    """Write a KB markdown file to disk, creating the project/task folder
    on the backend if it doesn't already exist.

    Args:
        project_name: used to build the top-level folder under kb_storage/
        task_name:    used to build the sub-folder under the project folder
        filename:     original filename (e.g. "notes.md")
        content:      raw text content of the .md file

    Returns:
        The absolute path of the file that was written.
    """
    project_slug = _slugify(project_name, default='general')
    task_slug = _slugify(task_name, default='untitled-task')

    folder = os.path.join(KB_ROOT, project_slug, task_slug)
    os.makedirs(folder, exist_ok=True)  # creates all missing parent folders too

    safe_name = filename or 'notes.md'
    if not safe_name.lower().endswith('.md'):
        safe_name += '.md'
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', safe_name)

    # Prefix with a timestamp so repeated saves for the same task never
    # overwrite each other -- every submission keeps its own file.
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    final_name = f"{timestamp}_{safe_name}"
    filepath = os.path.join(folder, final_name)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return filepath


def list_kb_files(project_name=None, task_name=None):
    """List KB files on disk, optionally scoped to a project and/or task.
    Useful for a future 'browse the KB' feature."""
    if not os.path.isdir(KB_ROOT):
        return []

    results = []
    project_dirs = [_slugify(project_name)] if project_name else os.listdir(KB_ROOT)
    for pdir in project_dirs:
        ppath = os.path.join(KB_ROOT, pdir)
        if not os.path.isdir(ppath):
            continue
        task_dirs = [_slugify(task_name)] if task_name else os.listdir(ppath)
        for tdir in task_dirs:
            tpath = os.path.join(ppath, tdir)
            if not os.path.isdir(tpath):
                continue
            for fname in sorted(os.listdir(tpath)):
                results.append(os.path.join(tpath, fname))
    return results


if __name__ == '__main__':
    # Quick manual test: run `python3 kb_storage.py` from the backend/
    # folder to confirm folder creation + file writing works on this host.
    path = save_kb_file(
        project_name='Demo Project',
        task_name='Fix login bug',
        filename='notes.md',
        content='# Demo\n\nThis is a test KB entry.\n',
    )
    print(f"Wrote: {path}")
    print("Files under kb_storage/:", list_kb_files())
