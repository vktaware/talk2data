import os
import pyodbc
import logging
import json # Import json for parsing LLM output
import datetime # Ensure the module is imported

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

# --- Session Management Constants ---
SESSION_EXPIRY_MINUTES = 30
MAX_HISTORY_MESSAGES = 20 # Keep last N messages (user + assistant)
SESSION_CLEANUP_INTERVAL_SECONDS = 600 # Run cleanup every 10 minutes

# --- In-Memory Session Storage ---
user_sessions = {}

def get_or_create_session(session_id: str) -> dict:
    """Retrieves or initializes session context for a user session ID."""
    # --- Import directly inside function --- 
    from datetime import datetime as dt_now_alias
    # --- Remove Debug Print ---
    # print(f"DEBUG (inside func): Type of 'datetime': {type(datetime)}, Value: {datetime}")
    now = dt_now_alias.now() # Use the aliased import
    if session_id not in user_sessions:
        logger.info(f"Creating new session: {session_id}")
        user_sessions[session_id] = {
            "history": [], # List of {'role': 'user'|'assistant', 'content': str}
            "extracted_entities": {"buyer_id": None}, # Store entities like product_name, order_no etc.
            "pending_action": None, # e.g., 'needs_product', 'needs_order_no'
            "original_query": None, # Store query that triggered pending_action
            "last_accessed": now # Use timestamp from aliased import
        }
    else:
        # Update timestamp on access
        user_sessions[session_id]["last_accessed"] = now
        # logger.debug(f"Found existing session: {session_id}")
    return user_sessions[session_id]

# --- Background Session Cleanup Task ---
async def cleanup_expired_sessions():
    """Periodically removes sessions that haven't been accessed recently."""
    # --- Import directly inside function --- 
    from datetime import datetime as dt_class, timedelta
    while True:
        await asyncio.sleep(SESSION_CLEANUP_INTERVAL_SECONDS)
        now = dt_class.now() # Use aliased import
        expiry_threshold = now - timedelta(minutes=SESSION_EXPIRY_MINUTES) # timedelta is fine
        expired_sessions = []
        
        # Safely identify expired sessions
        session_ids = list(user_sessions.keys()) # Copy keys to avoid mutation issues during iteration
        for session_id in session_ids:
            session = user_sessions.get(session_id) # Check if still exists
            if session and session.get("last_accessed", now) < expiry_threshold:
                expired_sessions.append(session_id)
                
        # Remove expired sessions
        if expired_sessions:
            logger.info(f"Cleaning up {len(expired_sessions)} expired sessions: {expired_sessions}")
            for session_id in expired_sessions:
                try:
                    del user_sessions[session_id]
                except KeyError:
                    logger.warning(f"Session {session_id} already removed during cleanup.")
        else:
            logger.debug("Session cleanup ran, no expired sessions found.")

# --- Configuration & Initialization ---

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

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
    title="TalkToData API (LangChain Fail-Safe)",
    description="API using LangChain LLM to query iTVFs, with fallback and post-processing.",
)

# --- Startup Event to Launch Background Task ---
@app.on_event("startup")
async def startup_event():
    logger.info("Starting background session cleanup task...")
    asyncio.create_task(cleanup_expired_sessions())

# CORS Configuration (keep as is)
origins = [
    "http://localhost:3000", # Keep if you might use port 3000
    "http://localhost:5173"  # Add the default Vite dev server port
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            conn.commit()

        cursor.close()
        conn.commit()

    except pyodbc.Error as db_ex:
        sqlstate = db_ex.args[0]
        error_message = f"Database execution error. SQLSTATE: {sqlstate}. Message: {db_ex}"
        logger.error(error_message)
        if conn:
            try: conn.rollback()
            except Exception: pass
        raise ConnectionError(f"{error_message}. Failed SQL: {sql}")
    except Exception as e:
        logger.error(f"Unexpected error during query execution: {e}", exc_info=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
        raise ConnectionError(f"Unexpected error during query execution: {e}. Failed SQL: {sql}")
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

    return results

# --- Prompt Template (for SQL Generation - Updated for Function Selection) ---
sql_gen_prompt_template = ChatPromptTemplate.from_messages([
    ("system",
     """You are an expert T-SQL assistant generating SQL Server queries to call specific table-valued functions.
{history} # Conversation history provides context.
Context: User may refer to entities mentioned earlier in the history.
**Goal:** Based on the user's *latest query* (`{question}`) and potentially the *history*, choose the single most appropriate function and generate the SQL to call it.
**Available Functions & Schemas:**
{schema}
**Process:**
1. **Analyze:** Understand the latest user query in the context of the history.
2. **Choose Function:** Select either `dbo.t2dFunc_GetBuyerProductDetails` or `dbo.t2dFunc_GetBuyerSaleOrderDetails`.
3. **Extract Parameters:** Identify the mandatory `@buyerId` and any optional parameters present in the query or implied by the history for the chosen function.
4. **Generate SQL:** Construct the `SELECT * FROM ChosenFunctionName(...)` statement using POSITIONAL arguments as specified in the schema. Ensure the *exact* number of arguments (values or `NULL`) is provided (31 for ProductDetails, 23 for SaleOrderDetails).
5. **Format Output (CRITICAL):** Your response MUST be **ONLY** a single JSON object containing THREE keys: `function_name` (string), `sql` (string), and `buyer_id` (integer). Do NOT include any explanations, introductory text, markdown formatting (like ```json), or anything else outside the single JSON object.

**Example of CORRECT Output:**
```json
{{"function_name": "dbo.t2dFunc_GetBuyerProductDetails", "sql": "SELECT * FROM dbo.t2dFunc_GetBuyerProductDetails(105, NULL, N'Some Product', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);", "buyer_id": 105}}
```

**Example of INCORRECT Output (Do NOT do this):**
Based on your request, I will use the Product Details function. Here is the JSON:
```json
{{"function_name": ... , "sql": ... , "buyer_id": ...}}
```
This query should give you the results.

**Strict Output Rule:** Respond ONLY with the valid JSON object and nothing else.
"""
     ),
    ("human", "{question}"), # This is the latest user query
])


# --- Prompt Template (for Data Processing - Updated with Context) ---
data_processing_prompt_template = ChatPromptTemplate.from_messages([
    ("system",
     """You are an assistant processing database results...
     {history} # Placeholder for history injection
     Analyze the user's *original question* in the context of the *conversation history* and the provided *database records* to formulate your answer.
     ...
     Data Type: {data_type}
     Database Records (JSON format):
     {db_results}
     ---
     """
     ),
    ("human", "Original Question: {question}") # 'question' here should be the initiating query of the turn
])


# --- Helper function for simple entity extraction (Example) ---
def extract_entities(query: str, session_entities: dict):
    """Placeholder for entity extraction logic. 
       Updates session_entities in place.
       Returns True if key entities seem present, False otherwise.
    """
    # Very basic extraction for now - enhance later with regex/NER
    updated_entities = session_entities.copy()
    query_lower = query.lower()
    
    # Attempt to find order number
    order_match = re.search(r'(order|buyer order)(?:\s+no|\s+number|\s+id)?\s+([a-zA-Z0-9\-]+)', query, re.IGNORECASE)
    if order_match:
        updated_entities['order_no'] = order_match.group(2)
        logger.info(f"Extractor found order_no: {updated_entities['order_no']}")

    # Attempt to find potential product descriptions/codes (simple example)
    # This needs significant improvement - consider keywords or patterns
    # Example: look for something after "product"
    product_match = re.search(r'product\s+(.+?)(?:\s+for|\s+buyer|$)', query, re.IGNORECASE)
    if product_match:
         potential_product = product_match.group(1).strip()
         # Avoid overwriting if already explicitly set by user response
         if not updated_entities.get('product_name'): 
              updated_entities['product_name'] = potential_product
              logger.info(f"Extractor found potential product_name: {updated_entities['product_name']}")

    # TODO: Add extraction for other entities like product code, etc.

    # Update the session entities
    session_entities.update(updated_entities)
    
    # Basic check if *something* relevant seems present (needs improvement)
    if updated_entities.get('order_no') or updated_entities.get('product_name') or updated_entities.get('product_code'):
        return True
    return False

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

# --- API Endpoints ---

@app.post("/api/login", response_model=LoginResponse)
async def login_user(request: LoginRequest):
    logger.info(f"Attempting login for user: {request.username} with session: {request.session_id}")

    if not DB_CONNECTION_STRING:
        logger.error("Database connection string not configured.")
        raise HTTPException(status_code=503, detail="Database connection not configured.")

    conn = None
    try:
        conn = pyodbc.connect(DB_CONNECTION_STRING, autocommit=True) # Autocommit is fine for SELECT
        cursor = conn.cursor()

        # IMPORTANT: Use parameterized query to prevent SQL injection
        query = """SELECT BuyerId 
                   FROM dbo.Affiliate 
                   WHERE UserName = ? AND Password = ? AND Deleted = 0"""
        
        cursor.execute(query, request.username, request.password)
        row = cursor.fetchone()

        cursor.close()

        if row and row.BuyerId is not None:
            logger.info(f"Login successful for user: {request.username}. BuyerId: {row.BuyerId}")
            
            # --- Update Session --- 
            session = get_or_create_session(request.session_id)
            session["extracted_entities"]["buyer_id"] = row.BuyerId
            # Optionally clear other entities/state on new login
            session["history"] = [] 
            session["pending_action"] = None
            session["original_query"] = None
            logger.info(f"Stored buyer_id {row.BuyerId} in session {request.session_id}")
            # ---------------------
            
            return LoginResponse(buyer_id=row.BuyerId)
        else:
            logger.warning(f"Login failed for user: {request.username}. Invalid credentials or user not found/inactive.")
            return LoginResponse(error="Invalid username or password")

    except pyodbc.Error as db_ex:
        logger.error(f"Database error during login for user {request.username}: {db_ex}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database error during login.")
    except Exception as e:
        logger.error(f"Unexpected error during login for user {request.username}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during login.")
    finally:
        if conn:
            conn.close()
            logger.debug(f"Database connection closed for login attempt: {request.username}")


@app.post("/api/query", response_model=QueryResponse)
async def query_database(request: QueryRequest):
    logger.info(f"Query received: '{request.user_query}' for session: {request.session_id}")
    session = get_or_create_session(request.session_id)
    current_buyer_id = session["extracted_entities"].get("buyer_id") # Get buyer_id safely

    # --- Ensure Buyer ID exists (From Login) ---
    if current_buyer_id is None:
        logger.warning(f"Access denied for session {request.session_id}: No Buyer ID found in session. User must log in.")
        # Return an error indicating login is required
        # Using 401 Unauthorized might be semantically correct, but requires frontend handling.
        # Returning a specific error message in the response might be simpler for now.
        return QueryResponse(query=None, answer="Login required to ask questions.", error="Authentication required")
        # raise HTTPException(status_code=401, detail="Authentication required. Please log in.") # Alternative

    # --- State Machine Logic ---
    user_query = request.user_query
    follow_up_response = None 

    if session["pending_action"]:
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
        # We will now proceed using the original_query + updated entities
        # For the LLM, the history now contains user_query -> follow_up -> user_response
        # We don't necessarily need to reconstruct the query string, the history provides context
        logger.info(f"Proceeding with original query context after getting follow-up info.")
        # Fall through to the main processing logic below

    else: # No pending action, process the query normally
        # Add current user query to history *before* processing
        session["history"].append({"role": "user", "content": user_query})

        # Attempt to extract entities from the current query
        extract_entities(user_query, session["extracted_entities"])
        logger.info(f"Session entities after extraction: {session['extracted_entities']}")

        # --- Check if we have enough info (Example Logic) ---
        # Basic intent detection (can be improved with LLM later if needed)
        query_lower = user_query.lower()
        is_product_query = any(k in query_lower for k in ["product", "generic", "ingredient", "rate", "brand"])
        is_order_query = any(k in query_lower for k in ["order", "status", "eta", "shipping"])

        needs_info = None
        if is_product_query and not (session["extracted_entities"].get('product_name') or session["extracted_entities"].get('product_code')):
            needs_info = 'product'
            follow_up_response = "Which product are you asking about? Please provide the name or code."
            session["pending_action"] = 'needs_product'
        elif is_order_query and not session["extracted_entities"].get('order_no'):
             # Check history first - maybe order was mentioned?
             # TODO: Add logic to check history for order no before asking
             needs_info = 'order_no'
             follow_up_response = "What is the Order Number you are referring to?"
             session["pending_action"] = 'needs_order_no'
        # TODO: Add more checks for other scenarios

        if needs_info:
            logger.warning(f"Query missing information: {needs_info}. Asking follow-up.")
            session["original_query"] = user_query # Store the query that needs info
            session["history"].append({"role": "assistant", "content": follow_up_response})
            return QueryResponse(query=None, answer=follow_up_response)

    # --- If we have enough info (or got it from follow-up), proceed to LLM --- 
    logger.info("Sufficient information detected or obtained. Proceeding to LLM SQL generation.")
    
    if initialization_error or llm is None:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {initialization_error or 'LLM not initialized'}")

    try:
        generated_sql_attempt1 = None
        chosen_function_name = None
        sql_to_execute = None
        results = []
        final_answer = None
        execution_error = None
        
        # == Step 1: Generate SQL using LLM ==
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
        
        # --- Parse and Validate LLM SQL Output --- 
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

        # == Step 1a: Attempt BuyerOrderNo Override (Python Regex) ==
        overridden_sql = generated_sql_attempt1 # Start with LLM's SQL
        if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
            try:
                latest_user_query = latest_user_query_for_llm # Use the query passed to LLM
                order_no_match = re.search(r'(?:order|buyer order)(?:\s+no|\s+number|\s+id)?\s+([a-zA-Z0-9\-]+)', latest_user_query, re.IGNORECASE)
                
                if order_no_match:
                    extracted_order_no_py = order_no_match.group(1)
                    logger.info(f"Python Regex extracted potential BuyerOrderNo: {extracted_order_no_py}")
                    quoted_order_no = f"N'{extracted_order_no_py}'"
                    
                    sql_match = re.search(r"\((.*)\)", generated_sql_attempt1)
                    if sql_match:
                        params_list = [p.strip() for p in sql_match.group(1).split(',')]
                        buyer_order_no_param_index = 19 
                        date_start_index = 21 
                        date_end_index = 22   
                        logger.debug(f"[Step 1a Debug] Parsed {len(params_list)} params. Target index: {buyer_order_no_param_index}")

                        correct_slot_is_null = False
                        if len(params_list) > buyer_order_no_param_index:
                            correct_slot_is_null = params_list[buyer_order_no_param_index].upper() == 'NULL'
                        logger.debug(f"[Step 1a Debug] Correct slot ({buyer_order_no_param_index}) is NULL: {correct_slot_is_null}")
                        
                        found_at_wrong_index = -1
                        for i, param in enumerate(params_list):
                            normalized_param = param.strip("N' ").lower() # Added space stripping
                            extracted_lower = extracted_order_no_py.lower()
                            if i != buyer_order_no_param_index and normalized_param == extracted_lower:
                                found_at_wrong_index = i
                                logger.debug(f"[Step 1a Debug] Found extracted order# ('{extracted_lower}') at wrong index: {found_at_wrong_index} (value: '{param}')")
                                break
                        logger.debug(f"[Step 1a Debug] Index found at wrong location: {found_at_wrong_index}")

                        if correct_slot_is_null and found_at_wrong_index != -1:
                            logger.info("[Step 1a Debug] Entering block to fix misplaced BuyerOrderNo...")
                            # Scenario: LLM put NULL in correct slot BUT put the value in the wrong slot
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
                            logger.info("[Step 1a Debug] Entering block for standard NULL override...")
                            # Scenario: LLM put NULL in correct slot, value not found elsewhere (original override case)
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
                            logger.warning("[Step 1a Debug] Found at wrong index, but correct slot was NOT NULL. No changes made.")
                        else:
                            logger.info("[Step 1a Debug] No condition met for override or fix.")
                    else:
                         logger.warning("Could not parse params from LLM SQL to check for BuyerOrderNo override.")
                else:
                    logger.info("Python Regex did not find BuyerOrderNo pattern in latest user query.")

            except Exception as override_ex:
                logger.error(f"Error during BuyerOrderNo override/fix attempt: {override_ex}", exc_info=True)
                # Keep overridden_sql as generated_sql_attempt1 on error
                
        generated_sql_attempt1 = overridden_sql # Pass potentially fixed/overridden SQL to next step

        # Initialize sql_to_execute with the result from Step 1a
        sql_to_execute = generated_sql_attempt1 

        # == Step 1b: Parameter Count Correction ==
        # (This step now runs on the potentially fixed SQL from Step 1a, held in generated_sql_attempt1/sql_to_execute)
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
        
        # == Step 2: Execute SQL ==
        try:
            results = execute_sql(sql_to_execute)
            logger.info(f"Attempt 1 SQL executed. Rows returned: {len(results)}")
        except ConnectionError as db_ex_1:
            logger.warning(f"Attempt 1 DB execution failed: {db_ex_1}")
            execution_error = str(db_ex_1)
            results = []

        # == Step 2b: Fallback Execution (BuyerID only) ==
        if not results and execution_error is None:
             logger.warning("Attempt 1 yielded no results. Triggering fallback (BuyerID only).")
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

        # == Step 3: Process Results with LLM ==
        data_type_context = "Product Details" if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails" else "Sales Order Details"

        if not results and execution_error is None:
            final_answer = f"I couldn't find any {data_type_context.lower()} matching your specific criteria (Buyer ID: {current_buyer_id})."
            if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                 final_answer += " Note: Sales order data is limited to the last 3 months."
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
                "db_results": results_json_str,
                "question": initiating_query, 
                "data_type": data_type_context,
                "history": formatted_history
            }
            data_processing_chain = data_processing_prompt_template | llm | StrOutputParser()
            final_answer = data_processing_chain.invoke(data_processing_input)
            logger.info(f"LLM processed answer: {final_answer}")

        # Add assistant response (either final answer or follow-up) to history
        assistant_response_content = final_answer if final_answer is not None else follow_up_response
        if assistant_response_content:
             session["history"].append({"role": "assistant", "content": assistant_response_content})
        else:
             # Handle cases where no response was generated (e.g., unexpected errors before response)
             logger.error("No assistant response content to add to history.") # Or add a generic error message

        # --- Enforce History Limit ---
        if len(session["history"]) > MAX_HISTORY_MESSAGES:
            logger.warning(f"History limit ({MAX_HISTORY_MESSAGES}) exceeded for session {request.session_id}. Truncating.")
            session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
        
        # Log final history size for debugging
        # logger.debug(f"Session {request.session_id} history size after update: {len(session['history'])}")
        
        # Return based on whether it was a follow-up or final answer
        if follow_up_response:
            return QueryResponse(query=None, answer=follow_up_response)
        else:
             logger.info(f"Final answer for session {request.session_id}: {final_answer}")
             return QueryResponse(query=sql_to_execute, answer=final_answer, error=None)

    except HTTPException as http_ex:
        # Log and re-raise specific HTTP exceptions
        logger.error(f"HTTP Exception in query endpoint: {http_ex.detail}")
        raise http_ex
    except Exception as e:
        # Catch-all for other unexpected errors during the main processing block
        logger.error(f"An unexpected error occurred in the query endpoint for session {request.session_id}: {e}", exc_info=True)
        # Ensure history includes the error message
        error_answer = f"An unexpected server error occurred: {e}"
        # Use a local variable for sql_to_return to handle potential NameError
        sql_to_return = None
        try:
            # Check if sql_to_execute was assigned before the error
            if 'sql_to_execute' in locals() and sql_to_execute is not None:
                 sql_to_return = sql_to_execute
            elif 'generated_sql_attempt1' in locals() and generated_sql_attempt1 is not None:
                 # Fallback: use the last known generated SQL if available
                 sql_to_return = generated_sql_attempt1
        except NameError:
            pass # Keep sql_to_return as None
            
        # Add error to history and apply limit
        if 'session' in locals(): # Ensure session exists before modifying history
            session["history"].append({"role": "assistant", "content": error_answer})
            if len(session["history"]) > MAX_HISTORY_MESSAGES:
                 session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
                 
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
    if initialization_error or llm is None:
         logger.critical(f"Cannot start server due to initialization error: {initialization_error or 'LLM not initialized'}")
         exit(1)

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 