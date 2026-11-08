import os

# Tests must never touch a real workspace database: the API tests clear the server's
# workspace, which by default persists to ~/.qaid/workspace.db.
os.environ["QAID_DB"] = ""
