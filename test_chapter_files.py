"""Test script to demonstrate the new chapter file structure."""

from pathlib import Path
from src.models.project import WriterProject, Manuscript, Chapter
import uuid
import shutil

def test_chapter_file_structure():
    """Test the new chapter file-based storage."""

    # Create a test project
    print("Creating test project...")
    project = WriterProject(
        name="Test Novel",
        description="Testing separate chapter files"
    )

    # Create manuscript with chapters
    project.manuscript = Manuscript(
        title="My Novel",
        author="Test Author"
    )

    # Add some chapters
    for i in range(1, 4):
        chapter = Chapter(
            id=str(uuid.uuid4()),
            number=i,
            title=f"Chapter {i}: The Adventure Begins" if i == 1 else f"Chapter {i}",
            content=f"This is the content of chapter {i}.\n\nIt has multiple paragraphs.\n\nAnd demonstrates the file-based storage."
        )
        project.manuscript.chapters.append(chapter)

    # Create test directory
    test_dir = Path("test_project")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()

    # Save project with separate chapter files
    print("Saving project with separate chapter files...")
    project_file = test_dir / "project.json"
    project.save_project(str(project_file), save_chapters_separately=True)

    # Check what was created
    print("\n=== Project Directory Structure ===")
    for path in sorted(test_dir.rglob("*")):
        if path.is_file():
            relative = path.relative_to(test_dir)
            size = path.stat().st_size
            print(f"  {relative} ({size} bytes)")

    # Load the project back
    print("\n=== Loading Project ===")
    loaded_project = WriterProject.load_project(str(project_file))

    print(f"Project: {loaded_project.name}")
    print(f"Manuscript: {loaded_project.manuscript.title}")
    print(f"Chapters loaded: {len(loaded_project.manuscript.chapters)}")

    for chapter in loaded_project.manuscript.chapters:
        print(f"\nChapter {chapter.number}: {chapter.title}")
        print(f"  File: {chapter.file_path}")
        print(f"  Content length: {len(chapter.content)} chars")
        print(f"  Content preview: {chapter.content[:50]}...")

    # Check project.json size
    json_size = project_file.stat().st_size
    print(f"\n=== Efficiency ===")
    print(f"project.json size: {json_size} bytes")

    total_chapter_size = sum(
        (test_dir / chapter.file_path).stat().st_size
        for chapter in loaded_project.manuscript.chapters
    )
    print(f"Total chapter files size: {total_chapter_size} bytes")
    print(f"Total project size: {json_size + total_chapter_size} bytes")

    print("\n✅ Test completed successfully!")
    print(f"\nProject saved to: {test_dir.absolute()}")

if __name__ == "__main__":
    test_chapter_file_structure()
