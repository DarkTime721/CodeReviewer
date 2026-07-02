import hashlib
from .graph.state import CodeReviewState, get_input_by_version, resolve_file_path
from .embeddings import client, collection


def collection_name_for_repo(repo_id: str) -> str:
    """Hash an arbitraty repo identifier into a name that satisfies
    ChromaDB's collection naming rules (alphanumeric/underscore/hyphen,
    3-63 chars, must start/end alphanumeric), with no risk of two
    different repos colliding onto the same collection."""

    canonical = repo_id.strip().rstrip('/').lower()
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"repo_{digest[:32]}"

embedding_fn = collection

def memory_writer(state: CodeReviewState):
    repo_id = state.get('repo_id') or 'unscoped'
    if repo_id == 'unscoped':
        print("memory_writer: no repo_id set — findings filed under shared 'unscoped' bucket")

    collection = client.get_or_create_collection(
        name=collection_name_for_repo(repo_id),
        embedding_function=embedding_fn
    )

    # Idempotent: lets you recover repo_id from the collection itself later,
    # since the collection's actual name on disk is just a hash
    try:
        collection.upsert(
            ids=["__manifest__"],
            documents=["repo manifest"],
            metadatas=[{"type": "manifest", "repo_id": repo_id}]
        )
    except Exception as e:
        print(f"memory_writer: manifest upsert failed: {e}")
    
    final_findings = state.get('final_findings') or []
    if not final_findings:
        return
    
    ids, documents, metadatas = [], [], []

    for index, finding in enumerate(final_findings):
        ids.append(f"{state['id']}_{index}")
        documents.append(f"{finding['agent']}\n{finding['description']}\n{finding['suggestion']}")
        metadatas.append({
            "file_path": finding['file_path'],
            "severity": finding['severity'],
            "line_number": finding['line_number'],
            "agent": finding['agent'],
        })

    try:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
    except Exception as e:
        print(f"memory_writer: failed to write findings for run {state['id']}: {e}")
    

def memory_reader(state: CodeReviewState):
    repo_id = state.get('repo_id') or 'unscoped'

    new_input = get_input_by_version(state['input'], 'new')
    if new_input is None:
        return {'previously_found': None, 'past_findings': []}
    
    current_file = resolve_file_path(new_input)

    try:
        collection = client.get_or_create_collection(
            name=collection_name_for_repo(repo_id),
            embedding_function= embedding_fn
        )

        results = collection.get(where={"file_path": current_file})
    except Exception as e:
        print(f"memory_reader: lookup failed: {e}")
        return {'previously_found': None}
    
    documents = results.get('documents', [])
    metadatas = results.get('metadatas', [])

    if not documents:
        return {'previously_found': None, 'past_findings': []}
    
    past_findings: dict[str, list[str]] = {}
    for doc, meta in zip(documents, metadatas):
        agent = meta.get('agent', 'Unknown')
        past_findings.setdefault(agent, []).append(doc)
    
    return {
        'previously_found': "\n\n".join(documents),
        'past_findings': past_findings
    }
