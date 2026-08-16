import subprocess

filter_script = r"c:\Users\ADITYA GUPTA\Downloads\DEP_main\filter_script.py"

cmd = [
    "git",
    "filter-branch",
    "-f",
    "--tree-filter",
    f'python "{filter_script}"',
    "HEAD",
    "main",
    "origin/main",
    "origin/backend_model"
]

print(f"Running command: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
if result.returncode != 0:
    print("FAILED")
    exit(1)
else:
    print("SUCCESS")
