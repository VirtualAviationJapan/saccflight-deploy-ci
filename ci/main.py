from pathlib import Path

if __name__ == "__main__":
    repo_dir = Path(__file__).parent().parent()
    gitmodules = repo_dir / ".gitmodules"

