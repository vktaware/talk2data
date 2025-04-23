import os
import pyodbc
import logging
import logging.handlers # Import handlers
import json # Import json for parsing LLM output AND REDIS
import datetime # Ensure the module is imported
import redis # Import Redis library

import decimal
import re # Import regex library
from urllib.parse import quote_plus # Keep for potential future use, but not needed for current approach
import asyncio # For background task
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field # Import Field for better validation
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
# Remove SQLDatabase and create_sql_query_chain imports
# from langchain_community.utilities import SQLDatabase
# from langchain.chains import create_sql_query_chain
# from sqlalchemy.engine import URL
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser # Add JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel as LangchainBaseModel # For structured output

# === Load Environment Variables FIRST ===
load_dotenv()
# ========================================

# --- Helper function for simple entity extraction (Example) ---
def extract_entities(query: str, session_entities: dict):
    """Placeholder for entity extraction logic.

    Updates session_entities in place.
    Returns True if key entities seem present, False otherwise.
    """
    # Very basic extraction for now - enhance later with regex/NER
    updated_entities = session_entities.copy() # Start with existing session entities
    query_lower = query.lower()
    
    # --- Reset potentially extracted entities for this turn --- 
    # Avoid carrying over product/order specifics from previous unrelated turns
    # Keep buyer_id as it persists from login
    updated_entities.pop('order_no', None)
    updated_entities.pop('product_code', None)
    updated_entities.pop('product_name', None)
    # --------------------------------------------------------

    # Attempt to find order number
    order_match = re.search(r'(order|buyer order)(?:\s+no|\s+number|\s+id)?\s+([a-zA-Z0-9\-]+)', query, re.IGNORECASE)
    if order_match:
        updated_entities['order_no'] = order_match.group(2)
        logger.info(f"Extractor found order_no: {updated_entities['order_no']}")

    # --- Attempt to find Product Code --- 
    # Pattern 1: Explicit "product code XXX"
    code_match_explicit = re.search(r'product\s+code\s+([a-zA-Z0-9\-_#]+)', query, re.IGNORECASE)
    # Pattern 2: Potential code - alphanumeric, no spaces, maybe min length (e.g., 5)
    # This is broader and might capture other numbers, adjust regex as needed
    # Using word boundaries (\b) to avoid matching parts of words
    code_match_implicit = re.search(r'\b([a-zA-Z0-9\-_#]{5,})\b', query) 

    potential_code = None
    if code_match_explicit:
        potential_code = code_match_explicit.group(1)
        logger.info(f"Extractor found explicit product_code: {potential_code}")
    elif code_match_implicit and not order_match: # Avoid capturing order number as code 
        # Check if the potential code is likely just a number (like quantity)
        # Simple check: avoid if it's purely digits and relatively short
        implicit_val = code_match_implicit.group(1)
        if not (implicit_val.isdigit() and len(implicit_val) < 5): # Adjust length threshold if needed
             potential_code = implicit_val
             logger.info(f"Extractor found potential implicit product_code: {potential_code}")
        
    if potential_code:
         updated_entities['product_code'] = potential_code
    # ----------------------------------

    # --- Attempt to find Product Name/Description (only if code wasn't found) ---
    if not potential_code:
        # Example: look for something after "product" or "details of" 
        # Avoid capturing the word "code" itself
        product_match_name = re.search(r'(?:product|details of)\s+(?!code\b)(.+?)(?:\s+for|\s+buyer|\s+code|$)', query, re.IGNORECASE)
        if product_match_name:
             potential_product_name = product_match_name.group(1).strip()
             # Avoid short strings that might just be qualifiers
             if len(potential_product_name) > 3: 
                  updated_entities['product_name'] = potential_product_name
                  logger.info(f"Extractor found potential product_name: {updated_entities['product_name']}")
    # ------------------------------------------------------------------------

    # Update the session entities definitively
    session_entities.update(updated_entities)
    
    # Basic check if *something* relevant seems present (needs improvement)
    if session_entities.get('order_no') or session_entities.get('product_name') or session_entities.get('product_code'):
        return True
    return False
# --------------------------------------------------------

# --- Format History for LLM --- 
def format_history_for_llm(history: list) -> str:
    """Formats the history list into a string for the LLM prompt."""
    if not history:
        return "No history available."
    
    formatted = "\n--- Conversation History ---\n"
    for turn in history:
        role = turn.get('role', 'unknown').capitalize()
        content = turn.get('content', '')
        formatted += f"{role}: {content}\n"
    formatted += "--- End History ---\n"
    return formatted
# -----------------------------

# --- Database Execution Helper (with type conversion) ---
def execute_sql(sql: str):
    """Executes the given SQL using pyodbc and returns results with basic type conversion."""
    # --- Import directly inside function --- 
    from datetime import datetime as dt_class, date
    
    results = []
    conn = None
    try:
        conn = pyodbc.connect(DB_CONNECTION_STRING, autocommit=False)
        cursor = conn.cursor()
        logger.info(f"Executing generated SQL query: {sql[:200]}...") # Log truncated SQL
        cursor.execute(sql)

        if cursor.description:
            columns = [column[0] for column in cursor.description]
            logger.info(f"Query executed successfully. Columns: {columns}")
            fetched_rows = cursor.fetchall()
            for row in fetched_rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    # Use aliased imports for isinstance check
                    if isinstance(val, (dt_class, date)):
                        row_dict[col] = val.isoformat()
                    elif isinstance(val, decimal.Decimal):
                        row_dict[col] = float(val)
                    elif isinstance(val, bytes):
                         try:
                             row_dict[col] = val.decode('utf-8') # Attempt to decode bytes
                         except UnicodeDecodeError:
                             row_dict[col] = f"<bytes data len={len(val)}>" # Placeholder if decode fails
                    else:
                        row_dict[col] = val
                results.append(row_dict)
            logger.info(f"Fetched {len(results)} rows.")
        else:
            logger.info("Query executed, but no rows returned by cursor.")
            # Commit might be needed for stored procedures that modify data even without returning rows
            conn.commit() 

        cursor.close()
        # Commit after closing cursor if using autocommit=False
        conn.commit() 

    except pyodbc.Error as db_ex:
        sqlstate = db_ex.args[0]
        error_message = f"Database execution error. SQLSTATE: {sqlstate}. Message: {db_ex}"
        logger.error(error_message)
        if conn:
            try: conn.rollback() 
            except Exception: pass # Ignore rollback errors if connection is broken
        # Raise a more specific error type to be caught in the endpoint
        raise ConnectionError(f"{error_message}. Failed SQL: {sql}") 
    except Exception as e:
        logger.error(f"Unexpected error during query execution: {e}", exc_info=True)
        if conn:
            try: conn.rollback() 
            except Exception: pass
        # Raise a more specific error type
        raise ConnectionError(f"Unexpected error during query execution: {e}. Failed SQL: {sql}") 
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

    return results
# ------------------------------------------------------

# --- Helper function for date range parsing ---
from datetime import date, timedelta, datetime
import re
import calendar

def parse_relative_date_range(text: str) -> tuple[str | None, str | None, bool]:
    """
    Parses common relative date phrases from text and returns (start_date, end_date, is_single_day)
    in 'YYYY-MM-DD' format, or (None, None, False) if no range is detected.
    """
    today = date.today()
    text_lower = text.lower()
    start_date, end_date = None, None
    is_single_day = False # Flag for specific day patterns

    # Simpler patterns first
    if "yesterday" in text_lower:
        start_date = today - timedelta(days=1)
        end_date = start_date
        is_single_day = True
    elif "today" in text_lower:
        start_date = today
        end_date = today
        is_single_day = True
    elif "last week" in text_lower:
        start_of_last_week = today - timedelta(days=today.weekday() + 7)
        end_of_last_week = start_of_last_week + timedelta(days=6)
        start_date = start_of_last_week
        end_date = end_of_last_week
    elif "last month" in text_lower:
        first_day_of_current_month = today.replace(day=1)
        last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        start_date = first_day_of_last_month
        end_date = last_day_of_last_month
    elif "last quarter" in text_lower:
        current_quarter = (today.month - 1) // 3 + 1
        # Determine start month of the *previous* quarter
        if current_quarter == 1:
            start_month_last_quarter = 10
            year_last_quarter = today.year - 1
        else:
            start_month_last_quarter = (current_quarter - 2) * 3 + 1
            year_last_quarter = today.year

        start_date_dt = datetime(year_last_quarter, start_month_last_quarter, 1)
        # Find end month and day of the previous quarter
        end_month_last_quarter = start_month_last_quarter + 2
        last_day = calendar.monthrange(year_last_quarter, end_month_last_quarter)[1]
        end_date_dt = datetime(year_last_quarter, end_month_last_quarter, last_day)
        start_date = start_date_dt.date()
        end_date = end_date_dt.date()

    # More complex patterns like "X days/weeks/months ago/back" or "last X days/weeks/months"
    match_ago = re.search(r'(\d+)\s+(day|week|month)s?\s+(ago|back)', text_lower)
    match_last_n = re.search(r'(last|past)\s+(\d+)\s+(day|week|month)s?', text_lower)

    if match_ago:
        num = int(match_ago.group(1))
        unit = match_ago.group(2)
        if unit == 'day':
            target_date = today - timedelta(days=num)
            start_date = target_date
            end_date = target_date # "X days ago" refers to a specific day
            is_single_day = True
        elif unit == 'week':
            target_date = today - timedelta(weeks=num)
            # Assume "X weeks ago" means that specific week Mon-Sun
            start_of_week = target_date - timedelta(days=target_date.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            start_date = start_of_week
            end_date = end_of_week
        elif unit == 'month':
             # Calculate the first day of the month 'num' months ago
             current_month = today.month
             current_year = today.year
             target_month = current_month - num
             target_year = current_year
             while target_month <= 0:
                 target_month += 12
                 target_year -= 1
             start_date_dt = datetime(target_year, target_month, 1)
             # Find the last day of that month
             last_day = calendar.monthrange(target_year, target_month)[1]
             end_date_dt = datetime(target_year, target_month, last_day)
             start_date = start_date_dt.date()
             end_date = end_date_dt.date()

    elif match_last_n:
        num = int(match_last_n.group(2))
        unit = match_last_n.group(3)
        if unit == 'day':
            start_date = today - timedelta(days=num - 1)
            end_date = today
        elif unit == 'week':
            # "Last N weeks" includes the current partial week up to today
            start_date = today - timedelta(weeks=num - 1)
            start_date = start_date - timedelta(days=start_date.weekday()) # Start of the Nth week back
            end_date = today
        elif unit == 'month':
            # "Last N months" includes the current partial month up to today
            current_month = today.month
            current_year = today.year
            start_month = current_month - (num - 1)
            start_year = current_year
            while start_month <= 0:
                 start_month += 12
                 start_year -= 1
            start_date = datetime(start_year, start_month, 1).date()
            end_date = today

    # Format dates if found
    start_date_str = start_date.isoformat() if start_date else None
    end_date_str = end_date.isoformat() if end_date else None

    if start_date_str or end_date_str:
        logger.info(f"Detected date range: Start={start_date_str}, End={end_date_str}, SingleDay={is_single_day}")

    return start_date_str, end_date_str, is_single_day
# --- Log Configuration ---
LOG_DIRECTORY = "logs"
LOG_FILENAME = "chat_Log.txt"
LOG_FILE_PATH = os.path.join(LOG_DIRECTORY, LOG_FILENAME)

# Ensure log directory exists
os.makedirs(LOG_DIRECTORY, exist_ok=True)

# Configure logging (replace basicConfig)
# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__) # Get logger instance
logger.setLevel(logging.INFO) # Set desired level (INFO, DEBUG, etc.)
logger.propagate = False # Prevent root logger handlers (like console) from duplicating messages if root is configured

# Create formatter
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s')

# Create Timed Rotating File Handler
# Rotates at midnight, keeps 7 backup logs
file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=LOG_FILE_PATH, 
    when='midnight', 
    interval=1, 
    backupCount=7, 
    encoding='utf-8'
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO) # Set level for the handler

# Add handler to the logger
logger.addHandler(file_handler)

# Optional: Add console handler back if you want logs both in file and console
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.DEBUG) # <--- Set to DEBUG temporarily
logger.addHandler(console_handler)

logger.info("--- Logging initialized --- Application starting ---")

# --- Session Management Constants ---
SESSION_EXPIRY_MINUTES = 30
SESSION_EXPIRY_SECONDS = SESSION_EXPIRY_MINUTES * 60 # Use seconds for Redis expiry
MAX_HISTORY_MESSAGES = 20 # Keep last N messages (user + assistant)
SESSION_CLEANUP_INTERVAL_SECONDS = 600 # Interval for in-memory cleanup

# --- Fallback In-Memory Session Storage ---
user_sessions = {} # Re-introduce for fallback
# -------------------------------------------

# --- Redis Configuration ---
REDIS_HOSTNAME = os.getenv("REDIS_HOSTNAME")
REDIS_PORT = os.getenv("REDIS_PORT", 6380)
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
redis_client = None # Client will hold the connection now
redis_connection_error = None

try:
    if not all([REDIS_HOSTNAME, REDIS_PASSWORD]):
        raise ValueError("Missing Redis configuration (REDIS_HOSTNAME, REDIS_PASSWORD) in environment settings.")

    logger.info(f"Attempting to connect to Redis at {REDIS_HOSTNAME}:{REDIS_PORT}")
    
    # Initialize the Redis client directly, specifying SSL options here
    redis_client = redis.Redis(
        host=REDIS_HOSTNAME,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        ssl=True, # Specify SSL connection
        ssl_cert_reqs='required', # Or None if verification causes issues, but required is safer
        db=0,
        decode_responses=False # Keep as False, handle encoding/decoding with JSON
    )
    
    # Test connection using the client instance
    redis_client.ping()
    logger.info("Successfully connected to Redis.")

except ValueError as ve:
    logger.critical(f"Redis Configuration Error: {ve}")
    redis_connection_error = str(ve)
except redis.exceptions.ConnectionError as ce:
    # Catch connection errors specifically during client init or ping
    logger.critical(f"Redis Connection Error: {ce}")
    redis_connection_error = f"Failed to connect to Redis: {ce}"
except TypeError as te:
    # Catch the specific TypeError if ssl/ssl_cert_reqs are still somehow invalid for the installed version
    logger.critical(f"Redis Initialization TypeError (likely SSL args): {te}. Check redis-py version compatibility.", exc_info=True)
    redis_connection_error = f"Redis init TypeError: {te}"
except Exception as e:
    logger.critical(f"Unexpected error initializing Redis: {e}", exc_info=True)
    redis_connection_error = f"Unexpected Redis initialization error: {e}"

# --- Session Saving Helper ---
def save_session(session_id: str, session_data: dict) -> bool:
    """Saves session data to Redis if available, otherwise to in-memory dict."""
    from datetime import datetime as dt_now_alias # Need this here too
    now = dt_now_alias.now()
    now_iso = now.isoformat()

    # Update last accessed time regardless of storage type
    # For Redis, store ISO string. For In-memory, store datetime object.
    session_data["last_accessed_iso"] = now_iso 
    session_data["last_accessed_dt"] = now 

    if redis_client and not redis_connection_error:
        # --- Save to Redis ---
        try:
            session_key = f"session:{session_id}"
            # Create a copy for Redis to avoid storing the 'dt' object
            redis_session_data = session_data.copy()
            redis_session_data.pop('last_accessed_dt', None) # Remove dt object before serializing
            
            session_data_updated_json = json.dumps(redis_session_data)
            redis_client.setex(session_key, SESSION_EXPIRY_SECONDS, session_data_updated_json.encode('utf-8'))
            logger.debug(f"Saved session {session_id} to Redis.")
            return True
        except redis.exceptions.RedisError as r_err:
            logger.error(f"Redis error saving session {session_id}: {r_err}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving session {session_id} to Redis: {e}", exc_info=True)
            return False
    else:
        # --- Save to In-Memory Dict --- 
        # The update to last_accessed_dt is already done above
        user_sessions[session_id] = session_data
        logger.debug(f"Saved session {session_id} to in-memory store.")
        return True
# --------------------------

def get_or_create_session(session_id: str) -> dict | None:
    """Retrieves session from Redis or initializes a new one, falling back to in-memory dict."""
    from datetime import datetime as dt_now_alias
    now = dt_now_alias.now()
    now_iso = now.isoformat()

    if redis_client and not redis_connection_error:
        # --- Try Redis First ---
        session_key = f"session:{session_id}" 
        try:
            session_data_bytes = redis_client.get(session_key)
            if session_data_bytes:
                session = json.loads(session_data_bytes.decode('utf-8'))
                logger.debug(f"Retrieved session {session_id} from Redis.")
                # Add dt object for consistency in return type, save happens later
                session["last_accessed_dt"] = now 
                return session
            else:
                # Create new session structure (will be saved by save_session later)
                logger.info(f"Creating new session structure for {session_id} (will save to Redis).")
                new_session = {
                    "history": [],
                    "extracted_entities": {"buyer_id": None},
                    "pending_action": None,
                    "original_query": None,
                    "last_accessed_iso": now_iso,
                    "last_accessed_dt": now # Add dt object
                }
                # Return the new structure; calling code MUST save it.
                return new_session
        except redis.exceptions.RedisError as r_err:
            logger.error(f"Redis error retrieving session {session_id}: {r_err}. Falling back to in-memory.", exc_info=True)
            # Fall through to in-memory logic below
        except json.JSONDecodeError as j_err:
             logger.error(f"Error decoding JSON for session {session_id} from Redis: {j_err}. Falling back to in-memory.", exc_info=True)
             # Fall through to in-memory logic below
        except Exception as e:
            logger.error(f"Unexpected error getting session {session_id} from Redis: {e}. Falling back to in-memory.", exc_info=True)
            # Fall through to in-memory logic below
    
    # --- Fallback to In-Memory Dict --- 
    logger.debug(f"Using in-memory session store for {session_id} (Redis unavailable or error occurred).")
    if session_id not in user_sessions:
        logger.info(f"Creating new session {session_id} in memory.")
        user_sessions[session_id] = {
            "history": [],
            "extracted_entities": {"buyer_id": None},
            "pending_action": None,
            "original_query": None,
            "last_accessed_iso": now_iso, # Keep ISO for potential future use
            "last_accessed_dt": now # Store datetime object for in-memory comparison
        }
    else:
        # Update last accessed time for existing in-memory session
        user_sessions[session_id]["last_accessed_dt"] = now
        logger.debug(f"Retrieved session {session_id} from memory.")
        
    return user_sessions[session_id]

# --- Background Session Cleanup Task (for In-Memory Fallback) ---
async def cleanup_expired_sessions():
    """Periodically removes sessions from the in-memory dict that haven't been accessed recently."""
    from datetime import datetime as dt_class, timedelta
    while True:
        await asyncio.sleep(SESSION_CLEANUP_INTERVAL_SECONDS)
        
        # Only run if Redis is NOT active
        if redis_client is None or redis_connection_error:
            now = dt_class.now() 
            expiry_threshold = now - timedelta(minutes=SESSION_EXPIRY_MINUTES)
            expired_sessions = []
            
            # Safely identify expired sessions from in-memory dict
            session_ids = list(user_sessions.keys()) # Avoid mutation issues
            for session_id in session_ids:
                session = user_sessions.get(session_id) 
                # Use 'last_accessed_dt' for comparison
                if session and session.get("last_accessed_dt", now) < expiry_threshold:
                    expired_sessions.append(session_id)
                    
            # Remove expired sessions
            if expired_sessions:
                logger.info(f"[In-Memory Cleanup] Removing {len(expired_sessions)} expired sessions: {expired_sessions}")
                for session_id in expired_sessions:
                    try:
                        del user_sessions[session_id]
                    except KeyError:
                        logger.warning(f"[In-Memory Cleanup] Session {session_id} already removed.")
            else:
                logger.debug("[In-Memory Cleanup] Ran, no expired sessions found.")
        else:
            logger.debug("[In-Memory Cleanup] Skipped - Redis is active.")
# ----------------------------------------------------------------------

# --- Prompt Template (for SQL Generation - Updated for Function Selection) ---
sql_gen_prompt_template = ChatPromptTemplate.from_messages([
    ("system",
     """You are an expert T-SQL assistant generating SQL Server queries to call specific table-valued functions.

**Conversation History:**
{history}

**Context Instructions:**
- Analyze the latest user query (`{question}`) below.
- CRITICALLY EXAMINE the conversation history provided above. The user might refer back to entities (products, orders, etc.) mentioned previously using pronouns ('it', 'this', 'that', 'the product', 'the order') or implicit references.
- Your primary goal is to resolve these references using the history to understand the *true* subject of the user's latest query.
- The Buyer ID is mandatory and should be available from the login context; do not generate SQL if it's missing (though Python handles this).

**Goal:** Based on the user's *latest query* (`{question}`) fully understood in the context of the *history*, choose the single most appropriate function and generate the SQL to call it.

**Available Functions & Schemas:**
{schema}

**Process:**
1. **Analyze Context:** Understand the latest user query `{question}` using the conversation `{history}`.
2. **Choose Function:** Select `dbo.t2dFunc_GetBuyerProductDetails` or `dbo.t2dFunc_GetBuyerSaleOrderDetails` based on the resolved query subject.
3. **Extract Parameters:** Identify the mandatory `@buyerId` and any optional parameters (e.g., ProductDescription, BuyerOrderNo) present in the query or clearly identified from the history.
4. **Generate SQL:** Construct the `SELECT * FROM ChosenFunctionName(...)` statement using POSITIONAL arguments. Ensure the *exact* number of arguments (31 for ProductDetails, 23 for SaleOrderDetails) using `NULL` for unspecified optional parameters.
5. **Format Output (CRITICAL):** Respond ONLY with a single valid JSON object containing THREE keys: `function_name` (string), `sql` (string), and `buyer_id` (integer). Do NOT include *any* other text, explanations, or markdown.

**Example CORRECT Output:**
```json
{{\"function_name\": \"dbo.t2dFunc_GetBuyerProductDetails\", \"sql\": \"SELECT * FROM dbo.t2dFunc_GetBuyerProductDetails(105, NULL, N'Some Product', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);\", \"buyer_id\": 105}}
```
"""
     ),
    ("human", "{question}"), # This is the latest user query
])


# --- Prompt Template (for Data Processing - Updated with Context) ---
data_processing_prompt_template = ChatPromptTemplate.from_messages([
    ("system",
     """You are an AI assistant interacting with a database based on user queries.
Given the user's query, conversation history, the executed SQL query, and the results from the database, formulate a concise and helpful answer.

Conversation History:
{history}

User Query: {user_query}

Executed SQL Query:
```sql
{executed_sql}
```

Database Results (JSON):
{db_results}

Session Entities (Context):
{entities}

Instructions:
1. Analyze the `db_results`.
2. If `db_results` is empty or `None`:
    - Check the `function_name` (`{function_name}`).
    - If it was a product search (`dbo.t2dFunc_GetBuyerProductDetails`), specifically state that the product could not be found based on the information provided (mentioning code or name if available in the user query or entities). Suggest trying different terms or providing more details.
    - If it was an order search (`dbo.t2dFunc_GetBuyerSaleOrderDetails`), state that no orders matching the criteria were found.
    - Otherwise, state that no information matching the query was found.
3. If `db_results` contains data:
    - Synthesize the information into a clear, natural language answer.
    - Do NOT just dump the raw data. Summarize or list key information relevant to the user query.
    - If multiple items are returned, list them concisely or summarize the key findings (e.g., "Found 5 products matching...", "Your last 3 orders are...").
    - Refer to specific fields from the results if helpful (e.g., "The price is $...", "Order status is 'Shipped'").
    - Use the `entities` dictionary provided above for context if needed (e.g., referring to the buyer ID).
4. Keep the answer concise and directly address the user's query.
5. Do not mention the SQL query unless the user specifically asked about it or there was an error related to it.
6. If the results seem ambiguous or potentially incomplete based on the query, mention this possibility briefly.

Answer:
"""
     ),
    ("human", "{user_query}") # Use the same key as provided in the input dictionary
])

# --- Configuration & Initialization ---

# Load environment variables
# load_dotenv() # <<< DELETE THIS LINE

# Get configuration values
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT_ID = os.getenv("AZURE_OPENAI_DEPLOYMENT_ID")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
DB_CONNECTION_STRING = os.getenv("DB_CONNECTION_STRING")
# TARGET_ITVF_NAMES_STR = os.getenv("TARGET_ITVF_NAMES") # No longer strictly needed for this approach

llm = None
# Remove db and sql_query_chain globals
# db = None
# sql_query_chain = None
initialization_error = None
# NUM_OPTIONAL_PARAMS = 30 # Number of optional params in the iTVF (after buyerId) - Determined dynamically now

# --- Manually Defined Schemas ---
# Combine schemas for both functions, clearly separated.
MANUAL_SCHEMAS = """
--- Function 1: Product Details ---
Function Name: dbo.t2dFunc_GetBuyerProductDetails
Parameters:
    @buyerId INT (Mandatory),
    @ProductCode NVARCHAR(255) = NULL,
    @ProductDescription NVARCHAR(255) = NULL,
    @USABrandName NVARCHAR(255) = NULL,
    @IndianBrandName NVARCHAR(255) = NULL,
    @GenericName NVARCHAR(255) = NULL,
    @Strength NVARCHAR(255) = NULL,
    @PackSize NVARCHAR(255) = NULL,
    @BoxSize NVARCHAR(255) = NULL,
    @Multiplier NVARCHAR(255) = NULL,
    @PackWeight NVARCHAR(255) = NULL,
    @BoxWeight NVARCHAR(255) = NULL,
    @Presentation NVARCHAR(255) = NULL,
    @CountryName NVARCHAR(255) = NULL,
    @Labelling NVARCHAR(255) = NULL,
    @HumanOrVetProduct NVARCHAR(255) = NULL,
    @ContentType NVARCHAR(255) = NULL,
    @JapaneseDescription NVARCHAR(255) = NULL,
    @GroupName NVARCHAR(255) = NULL,
    @Monograph4 NVARCHAR(255) = NULL,
    @MonographDesc NVARCHAR(255) = NULL,
    @BuyerCode NVARCHAR(255) = NULL,
    @AffiliateCode NVARCHAR(255) = NULL,
    @AffiliateName NVARCHAR(255) = NULL,
    @ProductIdentity NVARCHAR(255) = NULL,
    @Rate NVARCHAR(255) = NULL,
    @LastUpdateDate NVARCHAR(255) = NULL,
    @ManufacturerName NVARCHAR(255) = NULL,
    @DosageName NVARCHAR(255) = NULL,
    @MarketedByName NVARCHAR(255) = NULL,
    @UnitName NVARCHAR(255) = NULL
Description: Returns filtered product details, pricing, and affiliate information for a specific buyer ID. Use this for questions about product codes, descriptions, rates, brands, generic names, monograph files etc.

--- Function 2: Sales Order Details ---
Function Name: dbo.t2dFunc_GetBuyerSaleOrderDetails
Parameters:
    @buyerId INT (Mandatory),
    @ProductCode NVARCHAR(255) = NULL,
    @ProductDescription NVARCHAR(255) = NULL,
    @OrderStatus NVARCHAR(255) = NULL,
    @ManufacturerName NVARCHAR(255) = NULL,
    @MarketedByName NVARCHAR(255) = NULL,
    @DosageName NVARCHAR(255) = NULL,
    @UnitName NVARCHAR(255) = NULL,
    @USABrandName NVARCHAR(255) = NULL,
    @AffiliateCode NVARCHAR(255) = NULL,
    @AffiliateName NVARCHAR(255) = NULL,
    @ProductIdentity NVARCHAR(255) = NULL,
    @Rate NVARCHAR(255) = NULL,
    @LastUpdateDate NVARCHAR(255) = NULL,
    @OrderAmount NVARCHAR(255) = NULL,
    @ShippingFeeN NVARCHAR(255) = NULL,
    @DispensingFee NVARCHAR(255) = NULL,
    @BuyerCode NVARCHAR(255) = NULL,
    @OrderType NVARCHAR(255) = NULL,
    @BuyerOrderNo NVARCHAR(255) = NULL,
    @BuyerOrderDate NVARCHAR(255) = NULL,
    @BuyerOrderDateStart DATE = NULL,
    @BuyerOrderDateEnd DATE = NULL
Description: Returns sales order details for a specific buyer ID, limited to the last 3 months by default. Use this for questions about orders, status, ETAs, amounts, shipping, order dates, etc. Filter parameters can narrow results.
---
"""
logger.info(f"Using manually defined schemas (truncated):\n{MANUAL_SCHEMAS[:300]}...")


try:
    # 1. Initialize LLM
    if not all([AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_ID, AZURE_OPENAI_API_VERSION]):
        raise ValueError("Missing Azure OpenAI configuration in .env file.")

    llm = AzureChatOpenAI(
        openai_api_version=AZURE_OPENAI_API_VERSION,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_ID,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        temperature=0
    )
    logger.info("AzureChatOpenAI LLM initialized successfully.")

    # 2. Check DB Connection String exists
    if not DB_CONNECTION_STRING:
        raise ValueError("Missing DB_CONNECTION_STRING in .env file.")
    logger.info("DB connection string found.")

except Exception as e:
    logger.critical(f"Initialization failed: {e}", exc_info=True)
    initialization_error = str(e)

# --- Pydantic Models ---
class QueryRequest(BaseModel):
    user_query: str
    session_id: str # Added session ID

class SqlGenOutput(LangchainBaseModel):
    function_name: str = Field(description="The name of the selected SQL function (e.g., 'dbo.t2dFunc_GetBuyerProductDetails' or 'dbo.t2dFunc_GetBuyerSaleOrderDetails').")
    sql: str = Field(description="The generated T-SQL query.")
    buyer_id: int | None = Field(description="The extracted integer buyer ID.")
    # Optionally capture extracted filters for better fallback/logging
    # extracted_filters: dict | None = Field(default=None, description="Dictionary of extracted optional parameters.")

class QueryResponse(BaseModel):
    query: str | None # Final SQL query executed
    answer: str | None # Formatted answer from LLM post-processing
    error: str | None = None

class LoginRequest(BaseModel):
    username: str
    password: str
    session_id: str # Add session_id

class LoginResponse(BaseModel):
    buyer_id: int | None = None
    error: str | None = None

# --- FastAPI App ---
app = FastAPI(
    title="TalkToData API (Conditional Redis/In-Memory Sessions)",
    description="API using LangChain LLM to query iTVFs, with fallback, post-processing, and conditional Redis/in-memory sessions.",
)

# --- Startup Event to Conditionally Launch Background Task ---
@app.on_event("startup")
async def startup_event():
    if redis_client is None or redis_connection_error:
        logger.info("Redis unavailable, starting background in-memory session cleanup task...")
        asyncio.create_task(cleanup_expired_sessions())
    else:
         logger.info("Redis is available, background in-memory session cleanup task not needed.")
# ---------------------------------------------------------

# CORS Configuration (Add your origins here)
origins = [
    # ... your allowed origins ...
    "http://localhost:3000", 
    "http://localhost:5173",  
    "http://localhost:8080", 
    "https://localhost:8080", 
    "http://20.192.171.4",    
    "https://20.192.171.4"   
]
# ... CORSMiddleware setup ...

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*", "OPTIONS"], # Explicitly add OPTIONS
    allow_headers=["*"],
)

# --- API Endpoints ---

@app.post("/api/login", response_model=LoginResponse)
async def login_user(request: LoginRequest):
    # Mask password for logging
    log_request_details = {"username": request.username, "session_id": request.session_id, "password": "*****"}
    logger.info(f"Login request received: {log_request_details}")

    if not DB_CONNECTION_STRING:
        logger.error("Database connection string not configured.")
        raise HTTPException(status_code=503, detail="Database connection not configured.")

    conn = None
    try:
        logger.info("Attempting to connect to the database for login...")
        conn = pyodbc.connect(DB_CONNECTION_STRING, autocommit=True) # Autocommit is fine for SELECT
        logger.debug("Database connection successful for login.")
        cursor = conn.cursor()

        # IMPORTANT: Use parameterized query to prevent SQL injection
        query = """SELECT BuyerId 
                   FROM dbo.Affiliate 
                   WHERE UserName = ? AND Password = ? AND Deleted = 0"""
        
        cursor.execute(query, request.username, request.password)
        row = cursor.fetchone()

        cursor.close()

        if row and row.BuyerId is not None:
            logger.info(f"Login successful for user: {request.username}. Session: {request.session_id}, BuyerId: {row.BuyerId}")
            
            # --- Update Session using get_or_create and save_session ---
            session = get_or_create_session(request.session_id)
            if session is None:
                 logger.error(f"Failed to get/create session for session_id {request.session_id} during login.")
                 raise HTTPException(status_code=500, detail="Session management error during login.")

            # Update session details
            session["extracted_entities"]["buyer_id"] = row.BuyerId
            session["history"] = [] # Clear history on new login
            session["pending_action"] = None
            session["original_query"] = None

            # Save the updated session using the helper
            if not save_session(request.session_id, session):
                 logger.error(f"Failed to save updated session for session_id {request.session_id} after login.")
                 # Decide if login should fail here - maybe just log warning?
            else:
                 logger.info(f"Stored buyer_id {row.BuyerId} in session {request.session_id} ({'Redis' if redis_client and not redis_connection_error else 'In-Memory'})")
            # --------------------------------------------------------
            
            return LoginResponse(buyer_id=row.BuyerId)
        else:
            logger.warning(f"Login failed for user: {request.username} (Session: {request.session_id}). Invalid credentials or inactive.")
            return LoginResponse(error="Invalid username or password")

    except pyodbc.Error as db_ex:
        # Log the specific pyodbc error details
        logger.error(f"Caught pyodbc.Error during login for user {request.username}: {db_ex}")
        # Use logger.exception to include traceback in file log
        logger.exception(f"Database error during login for user {request.username} (Session: {request.session_id})")
        raise HTTPException(status_code=500, detail="Database error during login.")
    except Exception as e:
        # Log the specific generic exception details
        logger.error(f"Caught unexpected Exception during login for user {request.username}: {e}")
        # Use logger.exception here too
        logger.exception(f"Unexpected error during login for user {request.username} (Session: {request.session_id})")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during login.")
    finally:
        if conn:
            conn.close()
            # logger.debug(f"Database connection closed for login attempt: {request.username}") # Use debug level if desired
        logger.info("= = = = = End Login Request = = = = =") # Separator


@app.post("/api/query", response_model=QueryResponse)
async def query_database(request: QueryRequest):
    # Check Redis connection status (already done implicitly by get/save functions, but can keep explicit check)
    # if redis_client is None or redis_connection_error: ... (Optional check)

    log_request_details = {"user_query": request.user_query, "session_id": request.session_id}
    logger.info(f"Query request received: {log_request_details}")
    session = get_or_create_session(request.session_id) 

    if session is None:
        logger.error(f"Query request failed: Could not get/create session for {request.session_id}")
        raise HTTPException(status_code=500, detail="Session retrieval error.")

    current_buyer_id = session["extracted_entities"].get("buyer_id") 
    
    # --- Ensure Buyer ID exists (From Login) ---
    if current_buyer_id is None:
        logger.warning(f"Access denied for session {request.session_id}: No Buyer ID. User must log in.")
        # Log the attempt before returning
        return QueryResponse(query=None, answer="Login required to ask questions.", error="Authentication required")
    
    logger.info(f"Processing query for Buyer ID: {current_buyer_id}, Session: {request.session_id}")

    # --- State Machine Logic --- 
    user_query = request.user_query
    follow_up_response = None 
    sql_to_execute_for_log = None 
    final_answer_for_log = None 

    try: # Outer try for overall request processing
        if session["pending_action"]:
            # --- Handle User Response to Follow-up ---
            logger.info(f"Session {request.session_id} has pending action: {session['pending_action']}")
            pending_action = session["pending_action"]
            original_query = session["original_query"]
            user_response_to_follow_up = user_query # Current query is the answer

            # Add user's response to history
            session["history"].append({"role": "user", "content": user_response_to_follow_up})

            # Try to extract the missing info from the user's response
            if pending_action == 'needs_product':
                # Simplistic: Assume the response *is* the product name/code
                # A more robust approach would use regex/NER on user_response_to_follow_up
                session["extracted_entities"]['product_name'] = user_response_to_follow_up 
                logger.info(f"Extracted product '{user_response_to_follow_up}' from follow-up response.")
            elif pending_action == 'needs_order_no':
                # Simplistic: Assume response *is* the order number
                session["extracted_entities"]['order_no'] = user_response_to_follow_up 
                logger.info(f"Extracted order_no '{user_response_to_follow_up}' from follow-up response.")
            # TODO: Add cases for other pending actions

            # Clear pending state and use original query for context
            session["pending_action"] = None
            session["original_query"] = None
            logger.info(f"Proceeding with original query context after getting follow-up info.")
            # Save session after handling follow-up
            save_session(request.session_id, session)
            pass 

        # --- If no pending action, process normally ---
        else:
            # Add current user query to history *before* processing
            session["history"].append({"role": "user", "content": user_query})
            # Attempt to extract entities from the current query *first*
            
            extract_entities(user_query, session["extracted_entities"]) 
            # Save session after initial processing
            save_session(request.session_id, session)
            logger.info(f"Session entities after initial extraction: {session['extracted_entities']}")
            # NOTE: We removed the pre-LLM check for missing info here.

        # --- Proceed to LLM for SQL Generation ---
        logger.info("Proceeding to LLM SQL generation.")
        
        if initialization_error or llm is None:
            raise HTTPException(status_code=503, detail=f"Service unavailable: {initialization_error or 'LLM not initialized'}")

        # Inner try block for LLM calls, DB execution etc.
        # Initialize vars for this attempt
        generated_sql_attempt1 = None
        chosen_function_name = None
        sql_to_execute = None
        results = []
        final_answer = None
        execution_error = None
        attempted_code_as_name_fallback = False # Flag to prevent Buyer ID fallback if code->name worked

        try: # Inner try for LLM/DB processing
            # === Step 1: Generate SQL using LLM ===
            formatted_history = format_history_for_llm(session["history"])
            # Use the latest user message from history as the primary question for SQL gen
            # History itself provides context for pronouns etc.
            latest_user_query_for_llm = ""
            for msg in reversed(session["history"]):
                if msg.get('role') == 'user':
                    latest_user_query_for_llm = msg.get('content')
                    break
            if not latest_user_query_for_llm:
                latest_user_query_for_llm = user_query # Fallback if history is weird
                logger.warning("Could not find last user message in history, using current request query for LLM.")
            
            llm_input = {
                "schema": MANUAL_SCHEMAS,
                "question": latest_user_query_for_llm, 
                "history": formatted_history
            }
            logger.info(f"LLM Input for SQL Gen: {llm_input}")

            sql_gen_chain_raw = sql_gen_prompt_template | llm | StrOutputParser()
            raw_llm_output = sql_gen_chain_raw.invoke(llm_input)
            logger.info(f"Raw LLM output for SQL generation: {raw_llm_output}")
            
            # === Parse and Validate LLM SQL Output ===
            parsed_output_dict = None
            try:
                if raw_llm_output:
                    json_str = raw_llm_output.strip().strip("```json").strip("```").strip()
                    parsed_output_dict = json.loads(json_str)
                else:
                    raise ValueError("LLM returned empty output for SQL generation.")
                    
                if not isinstance(parsed_output_dict, dict) or 'sql' not in parsed_output_dict or 'function_name' not in parsed_output_dict:
                     raise ValueError(f"Parsed JSON from SQL LLM does not contain required keys ('sql', 'function_name'). Parsed: {parsed_output_dict}")
                     
                chosen_function_name = parsed_output_dict.get('function_name')
                generated_sql_attempt1 = parsed_output_dict.get('sql')
                sql_to_execute = generated_sql_attempt1 # Initial SQL
                
                try:
                    llm_buyer_id = int(parsed_output_dict.get('buyer_id'))
                    if llm_buyer_id != current_buyer_id:
                         logger.warning(f"LLM extracted buyer ID {llm_buyer_id} differs from session buyer ID {current_buyer_id}. Using session ID.")
                except (ValueError, TypeError, KeyError):
                    pass 

                if not chosen_function_name or chosen_function_name not in ["dbo.t2dFunc_GetBuyerProductDetails", "dbo.t2dFunc_GetBuyerSaleOrderDetails"]:
                     raise ValueError("LLM did not return a valid function_name in JSON.")
                if not generated_sql_attempt1 or not isinstance(generated_sql_attempt1, str):
                     raise ValueError("LLM did not return a valid SQL string in JSON.")

            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to decode LLM SQL output as JSON: {json_err}. Raw output: {raw_llm_output}", exc_info=True)
                raise HTTPException(status_code=400, detail=f"Failed to parse LLM response for SQL generation. Error: {json_err}")
            except Exception as gen_ex:
                logger.error(f"Failed during SQL generation/parsing: {gen_ex}. Raw output: {raw_llm_output}", exc_info=True)
                raise HTTPException(status_code=400, detail=f"Failed to generate/parse initial SQL query: {gen_ex}")

            # === NEW: Check for Missing Parameters AFTER LLM ===
            needs_info = None
            if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails":
                if not (session["extracted_entities"].get('product_name') or session["extracted_entities"].get('product_code')):
                    needs_info = 'product'
                    follow_up_response = "Which product are you asking about? Please provide the name or code."
                    session["pending_action"] = 'needs_product'
            elif chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                 if not session["extracted_entities"].get('order_no'):
                    needs_info = 'order_no'
                    follow_up_response = "What is the Order Number you are referring to?"
                    session["pending_action"] = 'needs_order_no'
            # TODO: Add checks for other functions if they exist

            if needs_info:
                logger.warning(f"Query requires info ({needs_info}) based on LLM function choice ({chosen_function_name}). Asking follow-up.")
                session["original_query"] = user_query # Store the query that needs info
                session["history"].append({"role": "assistant", "content": follow_up_response})
                # Apply history limit
                if len(session["history"]) > MAX_HISTORY_MESSAGES:
                    session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
                logger.info("= = = = = End Query Request (Follow-up) = = = = =") # Separator
                # Save session after asking follow-up
                save_session(request.session_id, session)
                return QueryResponse(query=None, answer=follow_up_response)
            # === END NEW CHECK ===

            # === Step 1a: BuyerOrderNo Override ===
            overridden_sql = generated_sql_attempt1 # Start with LLM's SQL
            if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                logger.debug("[Step 1a] Attempting BuyerOrderNo override...") # DEBUG
                try:
                    latest_user_query = latest_user_query_for_llm # Use the query passed to LLM
                    logger.debug(f"[Step 1a] Analyzing query for regex: {latest_user_query}") # DEBUG
                    order_no_match = re.search(r'(?:order|buyer order)(?:\s+no|\s+number|\s+id)?\s+([a-zA-Z0-9\-]+)', latest_user_query, re.IGNORECASE)
                    logger.debug(f"[Step 1a] Regex match result: {order_no_match}") # DEBUG
                    
                    if order_no_match:
                        extracted_order_no_py = order_no_match.group(1)
                        logger.info(f"[Step 1a] Python Regex extracted potential BuyerOrderNo: {extracted_order_no_py}") # INFO (already exists)
                        quoted_order_no = f"N'{extracted_order_no_py}'" 
                        
                        logger.debug(f"[Step 1a] Raw SQL from LLM: {generated_sql_attempt1}") # DEBUG
                        sql_match = re.search(r"\((.*)\)", generated_sql_attempt1)
                        if sql_match:
                            params_list = [p.strip() for p in sql_match.group(1).split(',')]
                            logger.debug(f"[Step 1a] Parsed params list (len={len(params_list)}): {params_list}") # DEBUG
                            buyer_order_no_param_index = 19 
                            date_start_index = 21 
                            date_end_index = 22   
                            # logger.debug(f"[Step 1a Debug] Parsed {len(params_list)} params. Target index: {buyer_order_no_param_index}") # Redundant

                            correct_slot_is_null = False
                            if len(params_list) > buyer_order_no_param_index:
                                correct_slot_is_null = params_list[buyer_order_no_param_index].upper() == 'NULL'
                            logger.debug(f"[Step 1a] Is correct slot ({buyer_order_no_param_index}) NULL? {correct_slot_is_null}") # DEBUG
                            
                            found_at_wrong_index = -1
                            for i, param in enumerate(params_list):
                                normalized_param = param.strip("N' ").lower() # Added space stripping
                                extracted_lower = extracted_order_no_py.lower()
                                if i != buyer_order_no_param_index and normalized_param == extracted_lower:
                                    found_at_wrong_index = i
                                    # logger.debug(f"[Step 1a Debug] Found extracted order# ('{extracted_lower}') at wrong index: {found_at_wrong_index} (value: '{param}')") # Redundant
                                    break
                            logger.debug(f"[Step 1a] Found extracted order# at wrong index? {found_at_wrong_index}") # DEBUG

                            if correct_slot_is_null and found_at_wrong_index != -1:
                                logger.debug("[Step 1a] Condition met: Fix misplaced BuyerOrderNo.") # DEBUG
                                # logger.info("[Step 1a Debug] Entering block to fix misplaced BuyerOrderNo...") # Redundant
                                logger.warning(f"Fixing misplaced BuyerOrderNo: Found '{params_list[found_at_wrong_index]}' at index {found_at_wrong_index}, expected at {buyer_order_no_param_index}.")
                                params_list[buyer_order_no_param_index] = quoted_order_no
                                params_list[found_at_wrong_index] = 'NULL' # Clear the wrong slot
                                # Ensure dates are NULL
                                if len(params_list) > date_end_index:
                                    params_list[date_start_index] = 'NULL'
                                    params_list[date_end_index] = 'NULL'
                                    logger.info("Ensured DateStart/End are NULL due to BuyerOrderNo fix.")
                                # Reconstruct SQL
                                prefix_match = re.match(r"(.*?\()", generated_sql_attempt1)
                                if prefix_match:
                                    prefix = prefix_match.group(1)
                                    overridden_sql = prefix + ", ".join(params_list) + ");"
                                    logger.info(f"SQL after BuyerOrderNo fix: {overridden_sql}")
                                else: 
                                    logger.error("Could not reconstruct SQL after fixing misplaced BuyerOrderNo.")
                            elif correct_slot_is_null:
                                logger.debug("[Step 1a] Condition met: Standard NULL override.") # DEBUG
                                # logger.info("[Step 1a Debug] Entering block for standard NULL override...") # Redundant
                                logger.warning(f"Overriding LLM's NULL for BuyerOrderNo with Python extracted value: {extracted_order_no_py}")
                                if len(params_list) > buyer_order_no_param_index:
                                    params_list[buyer_order_no_param_index] = quoted_order_no
                                    # Ensure dates are NULL
                                    if len(params_list) > date_end_index:
                                        params_list[date_start_index] = 'NULL'
                                        params_list[date_end_index] = 'NULL'
                                        logger.info("Ensured DateStart/End are NULL due to BuyerOrderNo override.")
                                    # Reconstruct SQL
                                    prefix_match = re.match(r"(.*?\()", generated_sql_attempt1)
                                    if prefix_match:
                                        prefix = prefix_match.group(1)
                                        overridden_sql = prefix + ", ".join(params_list) + ");"
                                        logger.info(f"SQL after BuyerOrderNo override: {overridden_sql}")
                                    else: 
                                        logger.error("Could not reconstruct SQL after BuyerOrderNo override.")
                                else:
                                    logger.error(f"Parameter list too short to apply BuyerOrderNo override at index {buyer_order_no_param_index}.")
                            elif found_at_wrong_index != -1:
                                # logger.warning("[Step 1a Debug] Found at wrong index, but correct slot was NOT NULL. No changes made.") # Redundant
                                logger.debug("[Step 1a] Condition met: Found at wrong index, but correct slot NOT NULL. No changes.") # DEBUG
                            else:
                                # logger.info("[Step 1a Debug] No condition met for override or fix.") # Redundant
                                logger.debug("[Step 1a] Condition met: No override/fix conditions met.") # DEBUG
                        else:
                             logger.warning("[Step 1a] Could not parse params from LLM SQL to check for BuyerOrderNo override.")
                    else:
                         logger.info("[Step 1a] Python Regex did not find BuyerOrderNo pattern in latest user query.")

                except Exception as override_ex:
                    logger.error(f"[Step 1a] Error during BuyerOrderNo override/fix attempt: {override_ex}", exc_info=True)
                    # Keep overridden_sql as generated_sql_attempt1 on error
                
            generated_sql_attempt1 = overridden_sql 
            
            # Initialize sql_to_execute AFTER Step 1a potentially modifies generated_sql_attempt1
            sql_to_execute = generated_sql_attempt1 

            # === Step 1b: Apply Parsed Date Range (if applicable) ===
            apply_date_filter = False # Flag to track if dates were parsed
            is_single_day_query = False # Flag for post-query filtering
            parsed_start_date_for_filter = None # Store the target date for filtering

            if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                parsed_start_date, parsed_end_date, is_single_day_query = parse_relative_date_range(latest_user_query_for_llm)
                parsed_start_date_for_filter = parsed_start_date # Store for potential post-filtering
                if parsed_start_date and parsed_end_date:
                    apply_date_filter = True # Dates were parsed, attempt SQL modification
                    logger.info(f"Applying parsed date range to SQL: {parsed_start_date} to {parsed_end_date}")
                    try:
                        sql_match = re.search(r"\((.*)\)", sql_to_execute) # Use current sql_to_execute
                        if sql_match:
                            params_list = [p.strip() for p in sql_match.group(1).split(',')]
                            buyer_order_no_param_index = 19 # 20th param
                            date_start_index = 21         # 22nd param
                            date_end_index = 22           # 23rd param

                            if len(params_list) > date_end_index: # Ensure list is long enough
                                # Set dates using standard SQL string format for dates
                                params_list[date_start_index] = f"\'{parsed_start_date}\'" # Use standard quotes
                                params_list[date_end_index] = f"\'{parsed_end_date}\'"   # Use standard quotes
                                # Clear BuyerOrderNo when using date range
                                params_list[buyer_order_no_param_index] = 'NULL' 
                                
                                # Reconstruct SQL
                                prefix_match = re.match(r"(.*?\()", sql_to_execute)
                                if prefix_match:
                                    prefix = prefix_match.group(1)
                                    sql_to_execute = prefix + ", ".join(params_list) + ");"
                                    logger.info(f"SQL after applying date range: {sql_to_execute}")
                                else: 
                                    logger.error("Could not reconstruct SQL after applying date range.")
                            else:
                                logger.error(f"Parameter list too short to apply date range override (found {len(params_list)}). SQL: {sql_to_execute}")
                        else:
                             logger.warning("Could not parse params from SQL to apply date range override.")
                    except Exception as date_override_ex:
                        logger.error(f"Error applying parsed date range to SQL: {date_override_ex}", exc_info=True)
                        # Proceed with potentially un-modified SQL

            # === Step 1c: Parameter Count Correction ===
            # (This step now runs on the potentially fixed SQL from Step 1a/1b, held in sql_to_execute)
            required_param_count = 0
            if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails":
                required_param_count = 31
            elif chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                required_param_count = 23
            
            if required_param_count > 0:
                try:
                    # Use generated_sql_attempt1 (the result of Step 1a) for the check
                    match = re.search(r"\((.*)\)", generated_sql_attempt1) 
                    if match:
                        params_str = match.group(1).strip()
                        actual_param_count = len(params_str.split(',')) if params_str else 0 
                        logger.info(f"Required params: {required_param_count}, Found params: {actual_param_count} in SQL from Step 1a")

                        if actual_param_count < required_param_count:
                            missing_params = required_param_count - actual_param_count
                            logger.warning(f"Correcting insufficient parameters: Adding {missing_params} NULLs.")
                            # Modify sql_to_execute based on check of generated_sql_attempt1
                            last_paren_index = generated_sql_attempt1.rfind(')')
                            if last_paren_index != -1:
                                nulls_to_add = ", NULL" * missing_params
                                if actual_param_count > 0: 
                                    sql_to_execute = generated_sql_attempt1[:last_paren_index] + nulls_to_add + generated_sql_attempt1[last_paren_index:]
                                else: 
                                    temp_sql = generated_sql_attempt1[:last_paren_index] + "NULL" * missing_params
                                    if missing_params > 1:
                                         temp_sql = temp_sql + (", NULL" * (missing_params - 1))
                                    sql_to_execute = temp_sql + generated_sql_attempt1[last_paren_index:]
                                logger.info(f"Corrected SQL (Added NULLs): {sql_to_execute}")
                            else:
                                logger.error("Could not find closing parenthesis in generated SQL to add NULLs.")
                                # sql_to_execute remains unchanged from Step 1a result
                        elif actual_param_count > required_param_count:
                            logger.warning(f"Correcting excessive parameters: Truncating extra parameters.")
                            # Modify sql_to_execute based on check of generated_sql_attempt1
                            params_list = [p.strip() for p in params_str.split(',')]
                            truncated_params_list = params_list[:required_param_count]
                            prefix_match = re.match(r"(.*?\()", generated_sql_attempt1)
                            if prefix_match:
                                prefix = prefix_match.group(1)
                                sql_to_execute = prefix + ", ".join(truncated_params_list) + ");"
                                logger.info(f"Corrected SQL (Truncated): {sql_to_execute}")
                            else:
                                logger.error("Could not reconstruct SQL after truncating parameters.")
                                # sql_to_execute remains unchanged from Step 1a result
                        # else: Parameter count is correct, sql_to_execute remains unchanged
                         
                    else:
                         logger.warning("Could not parse parameters using regex from SQL from Step 1a.")
                         # sql_to_execute remains unchanged

                except Exception as corr_ex:
                     logger.error(f"Error during parameter count correction: {corr_ex}", exc_info=True)
                     # sql_to_execute remains unchanged
            
            # === Step 2: Execute SQL (Multi-Attempt Logic for Product Details) ===
            results = []
            execution_error = None
            attempted_product_specific_search = False # Flag if we tried code or name
            successful_product_attempt = False # Flag if attempt 1 or 2 yielded results

            # --- Determine SQL for Attempt 1 --- 
            sql_attempt_1 = sql_to_execute # Start with the potentially corrected SQL from previous steps
            attempt_1_description = "LLM Default"
            
            if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails":
                extracted_code = session["extracted_entities"].get('product_code')
                extracted_name = session["extracted_entities"].get('product_name')
                
                # Decide if we are attempting a specific product search based on extraction
                if extracted_code or extracted_name:
                    attempted_product_specific_search = True
                
                try:
                    sql_match = re.search(r"\((.*)\)", sql_attempt_1)
                    if sql_match:
                        params_list = [p.strip() for p in sql_match.group(1).split(',')]
                        code_param_index = 1 # @ProductCode
                        desc_param_index = 2 # @ProductDescription
                        
                        if len(params_list) > desc_param_index: 
                            needs_reconstruction = False
                            if extracted_code:
                                # --- Prioritize Extracted Code --- 
                                attempt_1_description = f"Extracted Code: {extracted_code}"
                                escaped_code = extracted_code.replace("'", "''") 
                                quoted_code = f"'{escaped_code}'"
                                if params_list[code_param_index] != quoted_code or params_list[desc_param_index] != 'NULL':
                                    params_list[code_param_index] = quoted_code
                                    params_list[desc_param_index] = 'NULL'
                                    needs_reconstruction = True
                                    logger.info(f"Correcting SQL for Attempt 1: Using extracted code '{extracted_code}'.")
                            elif extracted_name:
                                # --- Use Extracted Name if No Code --- 
                                attempt_1_description = f"Extracted Name: {extracted_name}"
                                escaped_name = extracted_name.replace("'", "''")
                                quoted_name = f"'{escaped_name}'"
                                if params_list[desc_param_index] != quoted_name or params_list[code_param_index] != 'NULL':
                                    params_list[desc_param_index] = quoted_name
                                    params_list[code_param_index] = 'NULL'
                                    needs_reconstruction = True
                                    logger.info(f"Correcting SQL for Attempt 1: Using extracted name '{extracted_name}'.")
                            # Else: Use LLM default if neither extracted

                            if needs_reconstruction:
                                prefix_match = re.match(r"(.*?\()", sql_attempt_1)
                                if prefix_match:
                                    prefix = prefix_match.group(1)
                                    sql_attempt_1 = prefix + ", ".join(params_list) + ");"
                                else:
                                    logger.error(f"Could not reconstruct SQL for {attempt_1_description} attempt.")
                                    sql_attempt_1 = sql_to_execute # Revert on error
                        else:
                            logger.warning(f"Cannot correct SQL for Code/Name priority: Param list too short ({len(params_list)}).")
                    else:
                        logger.warning("Cannot correct SQL for Code/Name priority: Could not parse params.")
                except Exception as e:
                    logger.error(f"Error correcting SQL for Code/Name priority: {e}", exc_info=True)

                # --- Execute Attempt 1 (Code/Name or LLM Default) --- 
                logger.info(f"Executing SQL Attempt 1 ({attempt_1_description}): {sql_attempt_1}")
                sql_to_execute = sql_attempt_1 
                try:
                    results = execute_sql(sql_attempt_1)
                    logger.info(f"Attempt 1 SQL executed. Rows returned: {len(results)}")
                    if results: successful_product_attempt = True
                except ConnectionError as db_ex_1:
                    logger.warning(f"Attempt 1 DB execution failed: {db_ex_1}")
                    execution_error = str(db_ex_1)
                    results = [] 

                # --- Attempt 2: Fallback using Code as Description --- 
                # Only run if Attempt 1 used code, failed (0 results, no error), and code exists
                if attempted_product_specific_search and not successful_product_attempt and execution_error is None and extracted_code:
                    logger.warning(f"Attempt 1 (Code: {extracted_code}) failed. Trying code as description.")
                    sql_attempt_2 = "" 
                    try:
                        # Reconstruct SQL using the code in the description field
                        escaped_code_as_name = extracted_code.replace("'", "''")
                        quoted_code_as_name = f"'{escaped_code_as_name}'"
                        sql_match = re.search(r"\((.*)\)", sql_attempt_1) # Use Attempt 1 SQL structure
                        if sql_match:
                            params_list = [p.strip() for p in sql_match.group(1).split(',')]
                            if len(params_list) > desc_param_index:
                                params_list[code_param_index] = 'NULL'
                                params_list[desc_param_index] = quoted_code_as_name
                                
                                prefix_match = re.match(r"(.*?\()", sql_attempt_1)
                                if prefix_match:
                                    prefix = prefix_match.group(1)
                                    sql_attempt_2 = prefix + ", ".join(params_list) + ");"
                                    logger.info(f"Executing SQL Attempt 2 (Code as Name: {extracted_code}): {sql_attempt_2}")
                                    sql_to_execute = sql_attempt_2 
                                    try:
                                        results = execute_sql(sql_attempt_2)
                                        logger.info(f"Attempt 2 SQL executed. Rows returned: {len(results)}")
                                        if results: successful_product_attempt = True
                                    except ConnectionError as db_ex_2:
                                        logger.warning(f"Attempt 2 DB execution failed: {db_ex_2}")
                                        execution_error = str(db_ex_2) 
                                        results = [] 
                                else:
                                    logger.error("Could not reconstruct SQL prefix for Attempt 2.")
                            else:
                                logger.error("Param list too short for Attempt 2 SQL reconstruction.")
                        else:
                            logger.error("Could not parse params for Attempt 2 SQL reconstruction.")
                    except Exception as e2:
                         logger.error(f"Error preparing/executing SQL Attempt 2: {e2}", exc_info=True)
            else:
                # --- Standard Execution for non-ProductDetails functions --- 
                logger.info(f"Executing SQL for {chosen_function_name}: {sql_to_execute}")
                try:
                    results = execute_sql(sql_to_execute)
                    logger.info(f"SQL executed. Rows returned: {len(results)}")
                    if results: successful_product_attempt = True # Mark success even for non-product
                except ConnectionError as db_ex_std:
                    logger.warning(f"DB execution failed: {db_ex_std}")
                    execution_error = str(db_ex_std)
                    results = []
            # -----------------------------------------------------------------

            # === Step 2b: Fallback Execution (BuyerID only) ===
            # Run if no results AND no error AND EITHER it wasn't a product function OR the product-specific searches failed.
            if not results and execution_error is None and (not chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails" or not successful_product_attempt):
                 logger.warning(f"Previous attempts yielded no results (Product success: {successful_product_attempt}). Triggering fallback (BuyerID only).")
                 if current_buyer_id is not None and chosen_function_name is not None:
                    # Construct fallback SQL reliably for the *chosen* function
                    if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails":
                        num_optional_for_fallback = 30 
                    elif chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                        num_optional_for_fallback = 22 
                    else:
                        logger.error(f"Unknown function name '{chosen_function_name}' during fallback construction.")
                        raise HTTPException(status_code=500, detail="Internal configuration error during fallback.")

                    null_params = ", ".join(['NULL'] * num_optional_for_fallback)
                    fallback_sql = f"SELECT * FROM {chosen_function_name}({current_buyer_id}, {null_params});"
                    sql_to_execute = fallback_sql # Update the query to be executed/returned
                    logger.info(f"Constructed Fallback SQL: {fallback_sql}")
                    try:
                        results = execute_sql(fallback_sql)
                        logger.info(f"Fallback Attempt 2 executed. Rows returned: {len(results)}")
                    except ConnectionError as db_ex_2:
                        logger.error(f"Fallback Attempt 2 DB execution also failed: {db_ex_2}")
                        execution_error = str(db_ex_2) # Store fallback error
                        results = []
                 else:
                    logger.error("Cannot trigger fallback: BuyerID or Chosen Function Name missing.")
                    # Fallback failed, proceed to answer generation with empty results

            # === Step 2c: Post-Query Filtering for Single Day ===
            # Check if the query was for a single day and we have results and a target date
            if is_single_day_query and results and parsed_start_date_for_filter:
                original_count = len(results)
                # Assume the date column is named 'BuyerOrderDate' - ADJUST IF NEEDED
                order_date_column = 'BuyerOrderDate' 
                # Ensure date format consistency (YYYY-MM-DD)
                target_date_str = parsed_start_date_for_filter 
                
                filtered_results = []
                for row in results:
                    row_date_obj = row.get(order_date_column)
                    row_date_str = None
                    if isinstance(row_date_obj, str):
                        # Handle potential timestamp if DB returns datetime
                        row_date_str = row_date_obj.split('T')[0] if 'T' in row_date_obj else row_date_obj 
                    elif isinstance(row_date_obj, (date, datetime)):
                         # Handle date/datetime objects directly from pyodbc if conversion changes
                         row_date_str = row_date_obj.isoformat().split('T')[0]
                    
                    if row_date_str == target_date_str:
                        filtered_results.append(row)
                        
                if len(filtered_results) < original_count:
                    logger.info(f"Filtered results for single day ({target_date_str}): Kept {len(filtered_results)} out of {original_count} rows.")
                results = filtered_results # Replace original results with filtered list
            
            # === Step 3: Process Results with LLM ===
            data_type_context = "Product Details" if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails" else "Sales Order Details"

            if not results and execution_error is None:
                # Modify the response to remove Buyer ID
                final_answer = f"I couldn't find any {data_type_context.lower()} matching your specific criteria."
                if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                     final_answer += " Note: Sales order data is limited to the last 3 months by default if no date range is specified."
            elif execution_error:
                 final_answer = f"I encountered a database error trying to retrieve the {data_type_context.lower()}. Error: {execution_error}"
            else:
                logger.info(f"Processing {data_type_context} results with LLM...")
                MAX_ROWS_FOR_LLM = 50
                results_subset = results[:MAX_ROWS_FOR_LLM]
                if len(results) > MAX_ROWS_FOR_LLM:
                    logger.warning(f"Truncating results from {len(results)} to {MAX_ROWS_FOR_LLM} rows for LLM processing.")

                try:
                    results_json_str = json.dumps(results_subset, indent=2)
                except TypeError as json_err:
                    logger.error(f"Could not serialize database results to JSON: {json_err}")
                    raise HTTPException(status_code=500, detail="Failed to process database results.")

                formatted_history = format_history_for_llm(session["history"])
                # Use the query that *initiated* this turn for the 'question' context
                initiating_query = session["original_query"] or user_query
                data_processing_input = {
                    "history": formatted_history,
                    "user_query": initiating_query, # Use the query that started this interaction
                    "executed_sql": sql_to_execute, # The final SQL that was run
                    "db_results": results_json_str,
                    "entities": session["extracted_entities"], # Pass the current session entities
                    "function_name": chosen_function_name # Pass the function name used
                }
                data_processing_chain = data_processing_prompt_template | llm | StrOutputParser()
                final_answer = data_processing_chain.invoke(data_processing_input)
                logger.info(f"LLM processed answer: {final_answer}")
                final_answer_for_log = final_answer

            # Add assistant response (either final answer or follow-up) to history
            assistant_response_content = final_answer if final_answer is not None else follow_up_response
            if assistant_response_content:
                 session["history"].append({"role": "assistant", "content": assistant_response_content})
            else:
                 # Handle cases where no response was generated (e.g., unexpected errors before response)
                 logger.error("No assistant response content to add to history.") # Or add a generic error message

            # === Final steps after inner try block (success or handled error) ===
            # Add final assistant response/error to history
            assistant_response_content = final_answer_for_log if final_answer_for_log is not None else execution_error
            if assistant_response_content:
                 session["history"].append({"role": "assistant", "content": str(assistant_response_content)})
            else:
                 logger.error(f"No assistant response content to add to history for session {request.session_id}.")

            # Enforce History Limit
            if len(session["history"]) > MAX_HISTORY_MESSAGES:
                logger.warning(f"History limit ({MAX_HISTORY_MESSAGES}) exceeded for session {request.session_id}. Truncating.")
                session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
            
            # Log final outcome and add separator before returning success
            logger.info(f"Query processing finished for session {request.session_id}. Final Answer: {final_answer_for_log}, Error: {execution_error}")
            logger.info("= = = = = End Query Request (Success/Handled Error) = = = = =") # Separator
            return QueryResponse(query=sql_to_execute_for_log, answer=final_answer_for_log, error=execution_error)

        except HTTPException as http_ex_inner:
            logger.exception(f"HTTP Exception during query processing for session {request.session_id}")
            final_answer_for_log = f"Error processing request: {http_ex_inner.detail}"
            # Re-raise to be caught by outer handler potentially, or handle here
            raise http_ex_inner 
        except ConnectionError as conn_err:
            # Handle DB connection errors specifically if needed, otherwise caught by general Exception
             logger.exception(f"Database Connection Error during query processing for session {request.session_id}")
             final_answer_for_log = f"Database Error: {conn_err}"
             execution_error = str(conn_err)
             # Save session state before returning error
             save_session(request.session_id, session)
        except Exception as e_inner:
            logger.exception(f"Unexpected error during query processing for session {request.session_id}")
            final_answer_for_log = f"Unexpected processing error: {e_inner}"
            execution_error = str(e_inner)
            # Save session state before returning error
            save_session(request.session_id, session)

        # === Final steps after inner try block ===
        # Add final assistant response/error to history
        assistant_response_content = final_answer_for_log if final_answer_for_log is not None else execution_error
        if assistant_response_content:
             # Ensure history exists before appending
             if "history" not in session: session["history"] = [] 
             session["history"].append({"role": "assistant", "content": str(assistant_response_content)})
        else:
             logger.error(f"No assistant response content to add to history for session {request.session_id}.")

        # Enforce History Limit
        if len(session.get("history", [])) > MAX_HISTORY_MESSAGES:
            logger.warning(f"History limit ({MAX_HISTORY_MESSAGES}) exceeded for session {request.session_id}. Truncating.")
            session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
        
        # Log final outcome and add separator before returning success
        logger.info(f"Query processing finished for session {request.session_id}. Final Answer: {final_answer_for_log}, Error: {execution_error}")
        # Save final session state before returning response
        save_session(request.session_id, session)
        logger.info("= = = = = End Query Request (Success/Handled Error) = = = = =") 
        return QueryResponse(query=sql_to_execute_for_log, answer=final_answer_for_log, error=execution_error)

    except Exception as e_outer:
        logger.exception(f"Outer unexpected error in query endpoint for session {request.session_id}")
        error_answer = f"An unexpected server error occurred: {e_outer}"
        sql_to_return = None 
        # Add error to history and apply limit if session is available and valid
        if 'session' in locals() and isinstance(session, dict):
            if "history" not in session: session["history"] = []
            session["history"].append({"role": "assistant", "content": error_answer})
            if len(session["history"]) > MAX_HISTORY_MESSAGES:
                 session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
            # Save session state if possible before returning error
            save_session(request.session_id, session)
        logger.info("= = = = = End Query Request (Outer Error) = = = = =") 
        return QueryResponse(query=sql_to_return, answer=None, error=error_answer)


@app.get("/health", summary="Health Check")
async def health_check():
    """Basic health check endpoint."""
    status = "ok" if initialization_error is None and llm is not None else f"error: {initialization_error or 'LLM not initialized'}"
    return {"status": status}


# --- Run Server (keep as is) ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server with uvicorn...")
    if initialization_error or llm is None or redis_connection_error:
         final_error = initialization_error or 'LLM not initialized' or redis_connection_error
         logger.critical(f"Cannot start server due to initialization error: {final_error}")
         exit(1)

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True) 