import sqlite3

DB_FILE = "sniplink_practice.db"

def initialize_database() : 
    connection = sqlite3.connect(DB_FILE)

    try : 
        connection.execute("""
            CREATE TABLE IF NOT EXISTS links (
                short_code TEXT PRIMARY KEY NOT NULL,
                original_url TEXT NOT NULL,
                expires_at REAL,
                click_count INTEGER NOT NULL DEFAULT 0
            )
        """)

        rows = connection.execute(
            "PRAGMA table_info(links)"
        ).fetchall()

        column_names = [row[1] for row in rows]

        if "expires_at" not in column_names : 
            connection.execute(
                "ALTER TABLE links ADD COLUMN expires_at REAL"
            )

        if "click_count" not in column_names : 
            connection.execute(
                """
                ALTER TABLE links
                ADD COLUMN click_count INTEGER NOT NULL DEFAULT 0
                """
            )

        connection.commit()
    finally :
         connection.close()

def save_link(short_code, original_url, expires_at = None) : 
    connection = sqlite3.connect(DB_FILE)

    try : 
        connection.execute("""
            INSERT INTO links (short_code, original_url, expires_at) 
            VALUES (?, ?, ?)
        """,
        (short_code, original_url, expires_at)
        )
        connection.commit()
        return short_code
        # Here, ? -> placeholder 
        # We use this instead of fstring to avoid sql instruction from input, avoiding sql injections
    except sqlite3.IntegrityError as error : 
        raise ValueError("Short Code already exists") from error

    finally : 
        connection.close()

def find_link_details(short_code) : 
    connection = sqlite3.connect(DB_FILE)

    try : 
        cursor = connection.execute(
            """
            SELECT original_url, expires_at
            FROM links
            WHERE short_code = ?
            """,
            (short_code,)
        )
        row = cursor.fetchone()

        if row is None : 
            return None
        return {
            "short_code" : short_code,
            "original_url" : row[0],
            "expires_at" : row[1]
        }
    finally : 
        connection.close()

def find_link(short_code):
    details = find_link_details(short_code)

    if details is None:
        return None

    return details["original_url"]

def delete_link(short_code) : 
    connection = sqlite3.connect(DB_FILE)
    
    try : 
        cursor = connection.execute(
            """
            DELETE FROM links
            WHERE short_code = ?
            """,
            (short_code,)
        )
        deleted = cursor.rowcount
        connection.commit()

        if deleted == 0 : 
            return False
        return True
    finally : 
        connection.close()

def count_links() : 
    connection = sqlite3.connect(DB_FILE)

    try : 
        cursor = connection.execute(
            "SELECT COUNT(*) FROM links"
        )
        row = cursor.fetchone()
        return row[0]
    finally : 
        connection.close()

def record_click(short_code, expected_url, expected_expires_at) :
    connection = sqlite3.connect(DB_FILE)

    try : 
        cursor = connection.execute(
            """
            UPDATE links
            SET click_count = click_count + 1
            WHERE short_code = ?
                AND original_url = ?
                AND expires_at IS ?
            """,
            (short_code, expected_url, expected_expires_at)
        )
        connection.commit()

        return cursor.rowcount > 0
    finally : 
        connection.close()

def get_click_count(short_code) : 
    connection = sqlite3.connect(DB_FILE)

    try : 
        cursor = connection.execute(
            """
            SELECT click_count
            FROM links
            WHERE short_code = ?
            """,
            (short_code,)
        )
        row = cursor.fetchone()

        if row is None : 
            return None
        return row[0]

    finally : 
        connection.close()

if __name__ == "__main__" : 
    initialize_database()
