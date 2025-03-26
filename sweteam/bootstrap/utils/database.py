# database.py
#!/usr/bin/env python3
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Custom adapter and converter for datetime objects
def adapt_datetime(dt):
    """Convert datetime to ISO format string for SQLite storage."""
    return dt.isoformat()

def convert_datetime(s):
    """Convert ISO format string from SQLite back to datetime."""
    if not isinstance(s, str):
        return s
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return s

class DbTable:
    def __init__(self, db_conn, table_name: str, fields: Dict[str, str]):
        """
        Initialize a database table.
        
        Args:
            db_conn: SQLite database connection
            table_name: Name of the table
            fields: Dictionary mapping column names to their SQL data types/constraints
                   Example: {'id': 'TEXT PRIMARY KEY', 'name': 'TEXT NOT NULL'}
                   
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT NOT NULL'}
        >>> table = DbTable(conn, 'test_table', fields)
        >>> table.table_name
        'test_table'
        >>> table.fields == fields
        True
        """
        self.conn = db_conn
        self.table_name = table_name
        self.fields = fields
        
    def create(self) -> bool:
        """
        Create the table if it doesn't exist.
        
        Returns:
            bool: True if successful, False otherwise
            
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT NOT NULL'}
        >>> table = DbTable(conn, 'test_table', fields)
        >>> table.create()
        True
        >>> # Verify table exists by inserting data
        >>> cursor = conn.cursor()
        >>> csr=cursor.execute("INSERT INTO test_table (name) VALUES ('test')")
        >>> conn.commit()
        >>> cursor.execute("SELECT name FROM test_table").fetchone()[0]
        'test'
        """
        if not self.conn:
            return False
            
        try:
            cursor = self.conn.cursor()
            
            # Construct the CREATE TABLE statement from the fields dictionary
            fields_str = ', '.join([f"{field} {config}" for field, config in self.fields.items()])
            create_stmt = f"CREATE TABLE IF NOT EXISTS {self.table_name} ({fields_str})"
            
            cursor.execute(create_stmt)
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error creating table {self.table_name}: {e}")
            return False
            
    def insert(self, data: Dict[str, Any]) -> bool:
        """
        Insert data into the table.
        
        Args:
            data: Dictionary mapping column names to values
            
        Returns:
            bool: True if successful, False otherwise
            
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT NOT NULL', 'age': 'INTEGER'}
        >>> table = DbTable(conn, 'users', fields)
        >>> table.create()
        True
        >>> table.insert({'name': 'John Doe', 'age': 30})
        True
        >>> cursor = conn.cursor()
        >>> cursor.execute("SELECT name, age FROM users").fetchone()
        ('John Doe', 30)
        """
        if not self.conn:
            return False
            
        try:
            cursor = self.conn.cursor()
            
            # Get the columns that exist in both the data and the table fields
            valid_columns = [col for col in data.keys() if col in self.fields]
            
            # Prepare the INSERT statement
            columns_str = ', '.join(valid_columns)
            placeholders = ', '.join(['?' for _ in valid_columns])
            values = [data[col] for col in valid_columns]
            
            insert_stmt = f"INSERT OR REPLACE INTO {self.table_name} ({columns_str}) VALUES ({placeholders})"
            
            cursor.execute(insert_stmt, values)
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error inserting into table {self.table_name}: {e}")
            return False
            
    def select(self, columns: List[str] = None, where: Dict[str, Any] = None, 
               order_by: str = None, limit: int = None) -> Optional[List[Tuple]]:
        """
        Select data from the table.
        
        Args:
            columns: List of columns to select. If None, selects all columns.
            where: Dictionary of column-value pairs for WHERE clause
            order_by: Column name to order by (can include ASC/DESC)
            limit: Maximum number of rows to return
            
        Returns:
            List of tuples containing the queried data, or None if an error occurred
            
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT', 'age': 'INTEGER'}
        >>> table = DbTable(conn, 'people', fields)
        >>> table.create()
        True
        >>> table.insert({'name': 'Alice', 'age': 25})
        True
        >>> table.insert({'name': 'Bob', 'age': 30})
        True
        >>> table.insert({'name': 'Charlie', 'age': 35})
        True
        >>> result = table.select(columns=['name', 'age'], where={'age': 30})
        >>> result
        [('Bob', 30)]
        >>> result = table.select(order_by='age DESC', limit=2)
        >>> len(result)
        2
        >>> result[0][1]  # Name of person with highest age
        'Charlie'
        """
        if not self.conn:
            return None
            
        try:
            cursor = self.conn.cursor()
            
            # Prepare the SELECT statement
            if columns:
                valid_columns = [col for col in columns if col in self.fields]
                columns_str = ', '.join(valid_columns) if valid_columns else '*'
            else:
                columns_str = '*'
                
            query = f"SELECT {columns_str} FROM {self.table_name}"
            
            # Add WHERE clause if specified
            params = []
            if where:
                where_clauses = []
                for col, val in where.items():
                    if col in self.fields:
                        where_clauses.append(f"{col} = ?")
                        params.append(val)
                
                if where_clauses:
                    query += " WHERE " + " AND ".join(where_clauses)
            
            # Add ORDER BY clause if specified
            if order_by and any(col in order_by for col in self.fields):
                query += f" ORDER BY {order_by}"
                
            # Add LIMIT clause if specified
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query, params)
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error selecting from table {self.table_name}: {e}")
            return None


class Database:
    def __init__(self, db_name="twitter_sentiment.db"):
        """
        Initialize SQLite database connection.
        
        Args:
            db_name: Name of the database file
            
        >>> db = Database(':memory:')
        >>> db.db_name
        ':memory:'
        >>> db.tables
        {}
        """
        self.db_name = db_name
        self.conn = None
        self.tables = {}
        
    def connect(self) -> bool:
        """
        Connect to the SQLite database.
        
        Returns:
            bool: True if successful, False otherwise
            
        >>> db = Database(':memory:')
        >>> db.connect()
        True
        >>> isinstance(db.conn, sqlite3.Connection)
        True
        """
        try:
            # Register the datetime adapter and converter
            sqlite3.register_adapter(datetime, adapt_datetime)
            sqlite3.register_converter("TIMESTAMP", convert_datetime)
            
            # Use detect_types to enable type conversion, and isolation_level for explicit transactions
            self.conn = sqlite3.connect(
                self.db_name, 
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                isolation_level=None
            )
            
            # Enable foreign key constraints
            self.conn.execute("PRAGMA foreign_keys = ON")
            
            return True
        except sqlite3.Error as e:
            print(f"Database connection error: {e}")
            return False
    
    def create_table(self, table_name: str, fields: Dict[str, str]) -> Optional[DbTable]:
        """
        Create a new table in the database.
        
        Args:
            table_name: Name of the table
            fields: Dictionary mapping column names to their SQL data types/constraints
            
        Returns:
            DbTable instance or None if creation failed
            
        >>> db = Database(':memory:')
        >>> db.connect()
        True
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT NOT NULL'}
        >>> table = db.create_table('test_table', fields)
        >>> isinstance(table, DbTable)
        True
        >>> table.table_name
        'test_table'
        >>> 'test_table' in db.tables
        True
        """
        if not self.conn:
            if not self.connect():
                return None
        
        # Create a new DbTable instance
        table = DbTable(self.conn, table_name, fields)
        
        # Create the table in the database
        if table.create():
            # Store the table in the tables dictionary
            self.tables[table_name] = table
            return table
        return None
    
    def drop_table(self, table_name: str) -> bool:
        """
        Drop a table from the database and remove it from the tables collection.
        
        Args:
            table_name: Name of the table to drop
            
        Returns:
            bool: True if successful, False otherwise
            
        >>> db = Database(':memory:')
        >>> db.connect()
        True
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT NOT NULL'}
        >>> table = db.create_table('temp_table', fields)
        >>> 'temp_table' in db.tables
        True
        >>> db.drop_table('temp_table')
        True
        >>> 'temp_table' in db.tables
        False
        >>> # Verify table doesn't exist by trying to access it
        >>> cursor = db.conn.cursor()
        >>> try:
        ...    cursor.execute("SELECT * FROM temp_table")
        ...    failed = False
        ... except sqlite3.OperationalError:
        ...    failed = True
        >>> failed
        True
        """
        if not self.conn:
            if not self.connect():
                return False
        
        try:
            cursor = self.conn.cursor()
            
            # Drop the table from the database
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            self.conn.commit()
            
            # Remove the table from the tables collection if it exists
            if table_name in self.tables:
                del self.tables[table_name]
            
            #print(f"Table '{table_name}' dropped successfully")
            return True
        except sqlite3.Error as e:
            print(f"Error dropping table '{table_name}': {e}")
            return False
    
    def get_table(self, table_name: str) -> Optional[DbTable]:
        """
        Get a table by name.
        
        Args:
            table_name: Name of the table to retrieve
            
        Returns:
            DbTable instance or None if table doesn't exist
            
        >>> db = Database(':memory:')
        >>> db.connect()
        True
        >>> fields = {'id': 'INTEGER PRIMARY KEY', 'name': 'TEXT NOT NULL'}
        >>> tbl=db.create_table('users', fields)
        >>> table = db.get_table('users')
        >>> assert tbl is table
        >>> isinstance(table, DbTable)
        True
        >>> table.table_name
        'users'
        >>> db.get_table('nonexistent_table') is None
        True
        """
        return self.tables.get(table_name)
    
    # # Sample for how to use:
    # def create_tables(self) -> bool:
    #     """
    #     Create the default tweets table (for backward compatibility).
        
    #     Returns:
    #         bool: True if successful, False otherwise
            
    #     >>> db = Database(':memory:')
    #     >>> db.connect()
    #     True
    #     >>> db.create_tables()
    #     True
    #     >>> 'tweets' in db.tables
    #     True
    #     >>> # Verify table structure
    #     >>> db.tables['tweets'].fields['username']
    #     'TEXT NOT NULL'
    #     >>> db.tables['tweets'].fields['sentiment']
    #     'TEXT NOT NULL'
    #     """
    #     table = self.create_table('tweets', {
    #         'id': 'TEXT PRIMARY KEY',
    #         'username': 'TEXT NOT NULL',
    #         'created_at': 'TIMESTAMP NOT NULL',
    #         'text': 'TEXT NOT NULL',
    #         'sentiment': 'TEXT NOT NULL',
    #         'polarity': 'REAL NOT NULL',
    #         'analyzed_at': 'TIMESTAMP NOT NULL'
    #     })
    #     return table is not None
    
    # def insert_tweet(self, tweet_id, username, created_at, text, sentiment, polarity) -> bool:
    #     """
    #     Insert a tweet (for backward compatibility).
        
    #     Args:
    #         tweet_id: ID of the tweet
    #         username: Twitter username
    #         created_at: When the tweet was created
    #         text: Content of the tweet
    #         sentiment: Sentiment analysis result
    #         polarity: Sentiment polarity score
            
    #     Returns:
    #         bool: True if successful, False otherwise
            
    #     >>> from datetime import datetime
    #     >>> db = Database(':memory:')
    #     >>> db.connect()
    #     True
    #     >>> db.create_tables()
    #     True
    #     >>> now = datetime.now()
    #     >>> db.insert_tweet('123456', 'testuser', now, 'Hello world!', 'positive', 0.8)
    #     True
    #     >>> result = db.get_tweets_by_username('testuser')
    #     >>> len(result) > 0
    #     True
    #     >>> result[0][1]  # Username
    #     'testuser'
    #     >>> result[0][4]  # Sentiment
    #     'positive'
    #     """
    #     if 'tweets' not in self.tables:
    #         if not self.create_tables():
    #             return False
        
    #     tweets_table = self.tables['tweets']
    #     now = datetime.now()
        
    #     return tweets_table.insert({
    #         'id': tweet_id,
    #         'username': username,
    #         'created_at': created_at,
    #         'text': text,
    #         'sentiment': sentiment,
    #         'polarity': polarity,
    #         'analyzed_at': now
    #     })
    
    # def get_tweets_by_username(self, username) -> Optional[List[Tuple]]:
    #     """
    #     Retrieve tweets by username (for backward compatibility).
        
    #     Args:
    #         username: Twitter username to query for
            
    #     Returns:
    #         List of tuples containing tweet data, or None if an error occurred
            
    #     >>> from datetime import datetime
    #     >>> db = Database(':memory:')
    #     >>> db.connect()
    #     True
    #     >>> db.create_tables()
    #     True
    #     >>> now = datetime.now()
    #     >>> db.insert_tweet('123', 'user1', now, 'Tweet 1', 'positive', 0.5)
    #     True
    #     >>> db.insert_tweet('456', 'user1', now, 'Tweet 2', 'negative', -0.5)
    #     True
    #     >>> db.insert_tweet('789', 'user2', now, 'Tweet 3', 'neutral', 0.0)
    #     True
    #     >>> results = db.get_tweets_by_username('user1')
    #     >>> len(results)
    #     2
    #     >>> results[0][1]  # Username of first result
    #     'user1'
    #     >>> results = db.get_tweets_by_username('user2')
    #     >>> len(results)
    #     1
    #     >>> results[0][4]  # Sentiment of first result
    #     'neutral'
    #     """
    #     if 'tweets' not in self.tables:
    #         if not self.create_tables():
    #             return None
        
    #     tweets_table = self.tables['tweets']
    #     return tweets_table.select(
    #         where={'username': username},
    #         order_by='created_at DESC'
    #     )
    
    def close(self) -> None:
        """
        Close the database connection.
        
        >>> db = Database(':memory:')
        >>> db.connect()
        True
        >>> tbl=db.create_table('test', {'id': 'INTEGER PRIMARY KEY'})
        >>> type(tbl)
        <class '__main__.DbTable'>
        >>> len(db.tables) > 0
        True
        >>> db.close()
        >>> db.conn is None
        True
        >>> len(db.tables)
        0
        """
        if self.conn:
            self.conn.close()
            self.conn = None
            self.tables = {}

if __name__ == "__main__":
    import doctest
    doctest.testmod()