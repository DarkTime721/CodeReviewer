source_patterns = [
    # Flask
    ("request", ["args", "get"], 10),
    ("request", ["form", "get"], 10),
    ("request", ["json", "get"], 10),
    ("request", ["values", "get"], 10),
    ("request", ["headers", "get"], 8),
    ("request", ["cookies", "get"], 8),

    # Django
    ("request", ["GET", "get"], 10),
    ("request", ["POST", "get"], 10),
    ("request", ["FILES", "get"], 9),
    ("request", ["COOKIES", "get"], 8),
    ("request", ["META", "get"], 7),

    # FastAPI / Starlette
    ("Request", ["query_params", "get"], 10),
    ("Request", ["path_params", "get"], 10),
    ("Request", ["headers", "get"], 8),
    ("Request", ["cookies", "get"], 8),

    # CLI
    ("sys", ["argv"], 9),

    # Interactive
    ("input", [], 10),

    # Environment
    ("os", ["environ", "get"], 4),
    ("os", ["getenv"], 4),

    # Config files
    ("json", ["load"], 5),
    ("yaml", ["safe_load"], 5),

    # Deserialization
    ("pickle", ["load"], 8),
    ("pickle", ["loads"], 8),

    # Network
    ("socket", ["recv"], 9),
    ("socket", ["recvfrom"], 9),

    # HTTP
    ("requests", ["get"], 6),
    ("requests", ["post"], 6),

    # URL parsing
    ("urllib", ["parse_qs"], 8),
    ("urllib", ["parse_qsl"], 8),
]

sink_patterns = [
    # ========================
    # Command Execution
    # ========================
    ("os", ["system"], 10),
    ("os", ["popen"], 10),

    ("subprocess", ["run"], 10),
    ("subprocess", ["Popen"], 10),
    ("subprocess", ["call"], 10),
    ("subprocess", ["check_call"], 10),
    ("subprocess", ["check_output"], 10),

    # ========================
    # Code Execution
    # ========================
    ("eval", [], 10),
    ("exec", [], 10),

    ("compile", [], 9),
    ("__import__", [], 9),

    ("importlib", ["import_module"], 9),

    # ========================
    # Deserialization
    # ========================
    ("pickle", ["load"], 9),
    ("pickle", ["loads"], 9),

    ("yaml", ["load"], 8),

    ("marshal", ["load"], 9),
    ("marshal", ["loads"], 9),

    # ========================
    # SQL Injection
    # ========================
    ("cursor", ["execute"], 8),
    ("cursor", ["executemany"], 8),

    ("session", ["execute"], 8),
    ("engine", ["execute"], 8),

    ("conn", ["execute"], 8),
    ("connection", ["execute"], 8),

    # ========================
    # Template Injection
    # ========================
    ("jinja2", ["Template"], 8),
    ("Environment", ["from_string"], 8),

    # ========================
    # SSRF
    # ========================
    ("requests", ["get"], 7),
    ("requests", ["post"], 7),
    ("requests", ["request"], 7),

    ("urllib", ["urlopen"], 7),

    # ========================
    # File Operations
    # ========================
    ("open", [], 5),

    # ========================
    # Path Traversal
    # ========================
    ("shutil", ["copy"], 6),
    ("shutil", ["copyfile"], 6),
    ("shutil", ["move"], 6),

    # ========================
    # File Deletion
    # ========================
    ("os", ["remove"], 7),
    ("os", ["unlink"], 7),
    ("os", ["rmdir"], 7),

    ("shutil", ["rmtree"], 7),

    # ========================
    # Archive Extraction
    # ========================
    ("tarfile", ["extract"], 8),
    ("tarfile", ["extractall"], 8),

    ("zipfile", ["extract"], 8),
    ("zipfile", ["extractall"], 8),

    # ========================
    # Dynamic Attribute Access
    # ========================
    ("getattr", [], 6),
    ("setattr", [], 6),

    # ========================
    # XML Parsing
    # ========================
    ("ElementTree", ["parse"], 7),
    ("etree", ["parse"], 8),

    # ========================
    # Logging / Information Leak
    # ========================
    ("logging", ["info"], 4),
    ("logging", ["warning"], 4),
    ("logging", ["error"], 4),

    ("print", [], 3),
]
