def fetch_all(client, page_size=50):
    """Return every item from a paginated API."""
    items = []
    page = 1
    while True:
        batch = client.get("/items", params={"page": page, "size": page_size})
        if not batch:
            break
        items.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return items
