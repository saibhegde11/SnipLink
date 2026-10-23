import pytest
import storage_practice as storage

@pytest.fixture
def store(tmp_path, monkeypatch) : 
    test_db = tmp_path / "test_links.db"
    monkeypatch.setattr(storage, "DB_FILE", str(test_db))

    storage.initialize_database()
    return storage

def test_create_and_find(store) : 
    url = "https://docs.python.org/3/"
    code = store.save_link("docs", url)

    assert code == "docs"
    assert store.find_link("docs") == url
    assert store.count_links() == 1

def test_duplicate_keeps_original_mapping(store) : 
    original_url = "https://docs.python.org/3/"
    store.save_link("docs", original_url)

    with pytest.raises(ValueError) : 
        store.save_link("docs", "https://www.google.com")

    assert store.find_link("docs") == original_url
    assert store.count_links() == 1

def test_delete_preserves_other_links(store) : 
    url = "https://www.python.org"
    store.save_link("google", "https://www.google.com")
    store.save_link("python", url)

    assert store.delete_link("google") == True
    assert store.find_link("google") is None
    assert store.delete_link("google") == False
    assert store.find_link("python") == url  
    assert store.count_links() == 1

def test_click_counts(store) : 
    url1 = "https://docs.python.org/3/"
    code1 = store.save_link("docs", url1)

    assert code1 == "docs"
    assert store.find_link("docs") == url1

    url2 = "https://www.google.com"
    code2 = store.save_link("google", url2)

    assert code2 == "google"
    assert store.find_link("google") == url2

    assert store.count_links() == 2

    assert store.get_click_count("docs") == 0
    assert store.get_click_count("google") == 0

    assert store.record_click("docs", url1, None) == True
    assert store.record_click("docs", url1, None) == True
    assert store.record_click("google", url2, None) == True
    assert store.record_click("missing", url2, None) == False
    
    docs_count = store.get_click_count("docs")
    assert docs_count == 2
    
    google_count = store.get_click_count("google")
    assert google_count == 1

    missing_count = store.get_click_count("missing")
    assert missing_count is None






