import os
import pyodbc
import logging
import json # Import json for parsing LLM output
import datetime
import decimal
import re # Import regex library
from urllib.parse import quote_plus # Keep for potential future use, but not needed for current approach

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

class LoginResponse(BaseModel):
    buyer_id: int | None = None
    error: str | None = None

# --- FastAPI App ---
app = FastAPI(
    title="TalkToData API (LangChain Fail-Safe)",
    description="API using LangChain LLM to query iTVFs, with fallback and post-processing.",
)

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
                    if isinstance(val, (datetime.datetime, datetime.date)):
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
**Goal:** Based on the user's question and the available function schemas, choose the *single most appropriate* function and generate a `SELECT * FROM FunctionName(...)` statement to call it.
**Available Functions & Schemas:**
{schema}
**Process:**
1. **Choose Function:** Decide if the question is about Products (`dbo.t2dFunc_GetBuyerProductDetails`) or Sales Orders (`dbo.t2dFunc_GetBuyerSaleOrderDetails`). State the chosen function name.
2. **Extract BuyerID:** Identify the mandatory integer `buyerId`. If not found, fail.
3. **Extract Optional Filters:** Carefully read the user question again and identify if it contains values for ANY of the OPTIONAL parameters belonging to the CHOSEN function (Product Code, Order Number, Description, Brand Name, Status, etc.) Sometimes user may just say product (e.g. what is generic name of product VALCLOVIR 500 mg 10 Tab for buyer 105 here VALCLOVIR 500 mg 10 Tab is product description.).
4. **Parameter Mapping:** Create a list or mental map of the parameter values identified in steps 2 & 3.
5. **Handle BuyerOrderNo Exception:**  Buyerorder number may be called as buyer order or order number or order id or just order (e.g. in question what is status of order  344634521843-12345A for buyer 105? 344634521843-12345A is order number). Extract buyerorderno paramter according to regex patterngly. If calling `dbo.t2dFunc_GetBuyerSaleOrderDetails` AND you extracted a value for `@BuyerOrderNo`, ensure the values for `@BuyerOrderDateStart` and `@BuyerOrderDateEnd` are set to `NULL`, overriding any other date logic for those two specific parameters.
6. **Generate SQL (CRITICAL):** Construct the `SELECT * FROM ChosenFunctionName(...)` statement using POSITIONAL parameters.
    - Provide the extracted `@buyerId` value first.
    - **VERY IMPORTANT:** You MUST provide exactly the correct total number of arguments inside the parentheses for the chosen function:
        - `dbo.t2dFunc_GetBuyerProductDetails` requires **31** total arguments.
        - `dbo.t2dFunc_GetBuyerSaleOrderDetails` requires **23** total arguments.
    - For the chosen function, provide values for ALL subsequent parameters in the exact order they appear in the schema.
    - If you extracted a value for an optional parameter in step 3, place it in its correct position (quoting strings with N'...').
    - If you did NOT extract a value for an optional parameter, you MUST place `NULL` in its position.
    - **FAILURE TO PROVIDE THE EXACT NUMBER OF ARGUMENTS (values or NULLs) WILL CAUSE AN ERROR.**
7. **Format Output:** Respond with ONLY a JSON object containing THREE keys: `function_name` (the chosen function's name as string), `sql` (the generated `SELECT * FROM ...` statement as a string), and `buyer_id` (the extracted integer buyer ID).
**Example Output:**
```json
{{"function_name": "dbo.t2dFunc_GetBuyerSaleOrderDetails", "sql": "SELECT * FROM dbo.t2dFunc_GetBuyerSaleOrderDetails(105, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, N'3446843-23365610A', NULL, NULL, NULL);", "buyer_id": 105}}
```"""
     ),
    ("human", "{question}"),
])


# --- Prompt Template (for Data Processing - Updated with Context) ---
data_processing_prompt_template = ChatPromptTemplate.from_messages([
    ("system",
     """You are an assistant processing database results to answer a user's question.
You will be given the original question, the type of data retrieved (Product Details or Sales Order Details), and a list of data records (JSON string).
**Important Context:** Sales Order details are limited to the last 3 months of data from the source.
**Your Task:**
1. **Analyze Question & Data Type:** Understand the user's specific request and the type of data provided.
2. **Check for Monograph (Product Data):** IF data type is 'Product Details' AND user asked for ingredients/monograph, check 'Monograph4'/'MonographDesc' columns. If a path is found, state that the details are in the file: [path]. Do not summarize other fields.
3. **Check for Date Limit (Sales Order Data):** IF data type is 'Sales Order Details' AND the user asked for data explicitly older than 3 months (e.g., 'last year', 'show orders from 6 months ago'), first inform them the results are limited to the last 3 months due to system constraints, then proceed to answer based on the available data within that 3-month window if relevant. If the user asked about a specific Order Number, do not mention the 3-month limit unless specifically relevant to the answer.
4. **General Processing:** Otherwise, analyze the records to extract the specific information needed for the user's question. Focus on relevant columns based on the question (e.g., 'Rate' for cost, 'OrderStatus' for status, 'ProductCode', 'BuyerOrderNo', 'ETADate' etc.).
5. **Format Answer:** Present the answer clearly and concisely. If the specific information isn't in the records, state that. Base the answer ONLY on the provided records. Use formatting like lists or tables if it improves readability for multiple results.
---

Data Type: {data_type}

Database Records (JSON format):
{db_results}

---
"""
     ),
    ("human", "Original Question: {question}")
])


# --- API Endpoints ---

@app.post("/api/login", response_model=LoginResponse)
async def login_user(request: LoginRequest):
    logger.info(f"Attempting login for user: {request.username}")

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
    logger.info(f"Received query: '{request.user_query}'")

    if initialization_error or llm is None:
        error_detail = initialization_error or "LLM component not initialized."
        logger.error(f"Service unavailable: {error_detail}")
        raise HTTPException(status_code=503, detail=f"Service unavailable: {error_detail}")

    generated_sql_attempt1 = None
    extracted_buyer_id = None
    chosen_function_name = None
    sql_to_execute = None
    results = []
    final_answer = None
    execution_error = None

    try:
        # == Step 1: Generate Initial SQL (Attempt 1) ==
        logger.info("Generating initial SQL query (Attempt 1)...")
        
        # Define the chain to get raw string output first
        sql_gen_chain_raw = sql_gen_prompt_template | llm | StrOutputParser()
        
        raw_llm_output = None
        parsed_output_dict = None
        try:
            # Invoke chain to get raw string output
            raw_llm_output = sql_gen_chain_raw.invoke({
                "schema": MANUAL_SCHEMAS, # Use combined schemas
                "question": request.user_query
            })
            logger.info(f"Raw LLM output for SQL generation: {raw_llm_output}")

            # Attempt to parse the raw string as JSON
            if raw_llm_output:
                json_str = raw_llm_output.strip().strip("```json").strip("```").strip()
                parsed_output_dict = json.loads(json_str)
            else:
                 raise ValueError("LLM returned empty output.")

            # Validate the parsed dictionary has expected keys
            if not isinstance(parsed_output_dict, dict) or 'sql' not in parsed_output_dict or 'buyer_id' not in parsed_output_dict or 'function_name' not in parsed_output_dict:
                raise ValueError(f"Parsed JSON does not contain required keys ('sql', 'buyer_id', 'function_name'). Parsed: {parsed_output_dict}")

            # --- Extract data using dictionary access --- 
            chosen_function_name = parsed_output_dict.get('function_name') 
            generated_sql_attempt1 = parsed_output_dict.get('sql')
            # Ensure buyer_id is an integer
            try:
                extracted_buyer_id = int(parsed_output_dict.get('buyer_id'))
            except (ValueError, TypeError):
                raise ValueError(f"Extracted buyer_id '{parsed_output_dict.get('buyer_id')}' is not a valid integer.")
            
            sql_to_execute = generated_sql_attempt1 # Start with attempt 1
            
            # Further validation
            if not chosen_function_name or chosen_function_name not in ["dbo.t2dFunc_GetBuyerProductDetails", "dbo.t2dFunc_GetBuyerSaleOrderDetails"]:
                 raise ValueError("LLM did not return a valid function_name in JSON.")
            if not generated_sql_attempt1 or not isinstance(generated_sql_attempt1, str):
                 raise ValueError("LLM did not return a valid SQL string in JSON.")
            if extracted_buyer_id is None:
                 raise ValueError("LLM did not return a valid integer buyer_id in JSON.")
                 
            logger.info(f"Chosen Function: {chosen_function_name}")
            logger.info(f"Attempt 1 SQL (raw from LLM): {generated_sql_attempt1}")
            logger.info(f"Extracted Buyer ID: {extracted_buyer_id}")

        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode LLM output as JSON: {json_err}. Raw output: {raw_llm_output}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Failed to parse LLM response for SQL generation. Error: {json_err}")
        except Exception as gen_ex:
            logger.error(f"Failed during initial SQL generation/parsing: {gen_ex}. Raw output: {raw_llm_output}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Failed to generate/parse initial SQL query: {gen_ex}")
        
        # == Step 1a: Attempt BuyerOrderNo Override (Python Regex) ==
        overridden_sql = generated_sql_attempt1 # Start with LLM's SQL
        if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
            try:
                # Try to find BuyerOrderNo pattern in the original user query
                # Pattern looks for 'order', 'order no', 'order number', etc. followed by the identifier
                order_no_match = re.search(r'(?:order|buyer order)(?:\s+no|\s+number|\s+id)?\s+([a-zA-Z0-9\-]+)', request.user_query, re.IGNORECASE)
                
                if order_no_match:
                    extracted_order_no_py = order_no_match.group(1)
                    logger.info(f"Python Regex extracted potential BuyerOrderNo: {extracted_order_no_py}")
                    
                    # Now check if the LLM put NULL in the BuyerOrderNo slot (20th param total, index 19 after splitting)
                    # Use regex to find content within the main function call parentheses
                    sql_match = re.search(r"\((.*)\)", generated_sql_attempt1)
                    if sql_match:
                        params_list = [p.strip() for p in sql_match.group(1).split(',')]
                        buyer_order_no_param_index = 19 # 20th parameter, 0-indexed
                        
                        if len(params_list) > buyer_order_no_param_index and params_list[buyer_order_no_param_index].upper() == 'NULL':
                            logger.warning(f"Overriding LLM's NULL for BuyerOrderNo with Python extracted value: {extracted_order_no_py}")
                            params_list[buyer_order_no_param_index] = f"N'{extracted_order_no_py}'" # Add N'...' quoting
                            
                            # **Re-apply Special Handling**: Ensure DateStart/End are NULL if BuyerOrderNo is provided
                            date_start_index = 21 # 22nd param
                            date_end_index = 22   # 23rd param
                            if len(params_list) > date_end_index: # Check indices are valid
                                params_list[date_start_index] = 'NULL'
                                params_list[date_end_index] = 'NULL'
                                logger.info("Ensured DateStart/End are NULL due to BuyerOrderNo override.")
                            
                            # Reconstruct the SQL string
                            # Find the function name part to keep prefix
                            prefix_match = re.match(r"(.*?\()", generated_sql_attempt1)
                            if prefix_match:
                                prefix = prefix_match.group(1)
                                overridden_sql = prefix + ", ".join(params_list) + ");"
                                logger.info(f"SQL after BuyerOrderNo override: {overridden_sql}")
                            else: 
                                logger.error("Could not reconstruct SQL after override (prefix match failed).")
                                overridden_sql = generated_sql_attempt1 # Fallback if reconstruction fails
                        else:
                            logger.info("LLM provided a non-NULL BuyerOrderNo or param index invalid, no override needed.")
                    else:
                         logger.warning("Could not parse params from LLM SQL to check for BuyerOrderNo override.")
                else:
                    logger.info("Python Regex did not find BuyerOrderNo pattern in user query.")

            except Exception as override_ex:
                logger.error(f"Error during BuyerOrderNo override attempt: {override_ex}", exc_info=True)
                overridden_sql = generated_sql_attempt1 # Fallback to original SQL on error
                
        # Pass the potentially overridden SQL to the next step
        generated_sql_attempt1 = overridden_sql

        # == Step 1b: Validate and Correct Parameter Count ==
        required_param_count = 0
        if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails":
            required_param_count = 31
        elif chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
            required_param_count = 23
        
        corrected_sql = generated_sql_attempt1 # Start with the original
        if required_param_count > 0:
            try:
                # Use regex to find content within the main function call parentheses
                match = re.search(r"\((.*)\)", generated_sql_attempt1)
                if match:
                    params_str = match.group(1).strip()
                    # Count parameters by splitting on comma, handle empty string case
                    actual_param_count = len(params_str.split(',')) if params_str else 0 
                    logger.info(f"Required params: {required_param_count}, Found params: {actual_param_count}")

                    if actual_param_count < required_param_count:
                        missing_params = required_param_count - actual_param_count
                        logger.warning(f"LLM generated insufficient parameters. Adding {missing_params} NULLs.")
                        # Find the position of the last closing parenthesis
                        last_paren_index = generated_sql_attempt1.rfind(')')
                        if last_paren_index != -1:
                            # Construct the NULLs to add
                            nulls_to_add = ", NULL" * missing_params
                            # If there were existing params, add comma before NULLs
                            if actual_param_count > 0: 
                                corrected_sql = generated_sql_attempt1[:last_paren_index] + nulls_to_add + generated_sql_attempt1[last_paren_index:]
                            else: # Handle case where LLM might generate func() with no params
                                corrected_sql = generated_sql_attempt1[:last_paren_index] + "NULL" * missing_params # Add first NULL without comma
                                if missing_params > 1:
                                     corrected_sql = corrected_sql[:last_paren_index] + (", NULL" * (missing_params - 1)) + corrected_sql[last_paren_index:]
                            logger.info(f"Corrected SQL: {corrected_sql}")
                        else:
                            logger.error("Could not find closing parenthesis in generated SQL to correct params.")
                            # Fallback or raise error - maybe use original SQL and let DB fail?
                            corrected_sql = generated_sql_attempt1 
                    elif actual_param_count > required_param_count:
                        logger.warning(f"LLM generated TOO MANY parameters ({actual_param_count} vs {required_param_count}). Truncating extra parameters.")
                        # Truncate the list of parameters
                        params_list = [p.strip() for p in params_str.split(',')]
                        truncated_params_list = params_list[:required_param_count]
                        
                        # Reconstruct the SQL string with the correct number of parameters
                        # Find the function name part to keep prefix
                        prefix_match = re.match(r"(.*?\()", generated_sql_attempt1)
                        if prefix_match:
                            prefix = prefix_match.group(1)
                            corrected_sql = prefix + ", ".join(truncated_params_list) + ");"
                            logger.info(f"Corrected SQL (truncated): {corrected_sql}")
                        else:
                            logger.error("Could not reconstruct SQL after truncating parameters (prefix match failed).")
                            corrected_sql = generated_sql_attempt1 # Fallback if reconstruction fails
                    else:
                         # Count is correct, no changes needed
                         corrected_sql = generated_sql_attempt1 # Ensure corrected_sql has the right value
                         pass
                else:
                     logger.warning("Could not parse parameters using regex from generated SQL.")
                     # Use original SQL and let DB handle error
                     corrected_sql = generated_sql_attempt1

            except Exception as corr_ex:
                 logger.error(f"Error during parameter count correction: {corr_ex}", exc_info=True)
                 corrected_sql = generated_sql_attempt1 # Fallback to original SQL on correction error
        
        # Use the potentially corrected SQL for execution
        generated_sql_attempt1 = corrected_sql
        sql_to_execute = generated_sql_attempt1 # Update the sql_to_execute as well

        # == Step 2: Execute Initial SQL (Attempt 1) ==
        try:
            results = execute_sql(generated_sql_attempt1)
            logger.info(f"Attempt 1 executed. Rows returned: {len(results)}")
        except ConnectionError as db_ex_1:
            logger.warning(f"Attempt 1 DB execution failed: {db_ex_1}")
            execution_error = str(db_ex_1)
            results = []

        # == Step 2b: Fallback Execution (Attempt 2) if needed ==
        # Fallback ONLY if attempt 1 returned NO rows (not if it errored)
        if not results and execution_error is None:
             logger.warning("Attempt 1 yielded no results. Triggering fallback (BuyerID only).")
             if extracted_buyer_id is not None and chosen_function_name is not None:
                # Construct fallback SQL reliably for the *chosen* function
                if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails":
                    num_optional_for_fallback = 30 # 31 total - 1 buyerId
                elif chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                    num_optional_for_fallback = 22 # <-- Corrected: 23 total - 1 buyerId = 22 optional
                else:
                    # Should not happen due to validation, but safety check
                    logger.error(f"Unknown function name '{chosen_function_name}' during fallback construction.")
                    raise HTTPException(status_code=500, detail="Internal configuration error during fallback.")

                null_params = ", ".join(['NULL'] * num_optional_for_fallback)
                fallback_sql = f"SELECT * FROM {chosen_function_name}({extracted_buyer_id}, {null_params});"

                sql_to_execute = fallback_sql # Update the query to be executed/returned
                logger.info(f"Constructed Fallback SQL: {fallback_sql}")
                try:
                    results = execute_sql(fallback_sql)
                    logger.info(f"Fallback Attempt 2 executed. Rows returned: {len(results)}")
                    # Keep execution_error as None since fallback didn't error here
                except ConnectionError as db_ex_2:
                    logger.error(f"Fallback Attempt 2 DB execution also failed: {db_ex_2}")
                    execution_error = str(db_ex_2) # Store fallback error
                    results = []
             else:
                logger.error("Cannot trigger fallback: BuyerID or Chosen Function Name missing from Step 1.")
                # This implies Step 1 failed badly, use its error
                raise HTTPException(status_code=400, detail="Failed to generate initial query details needed for fallback.")

        # == Step 3: Process Results with LLM ==
        data_type_context = "Product Details" if chosen_function_name == "dbo.t2dFunc_GetBuyerProductDetails" else "Sales Order Details"

        if not results and execution_error is None:
            # If results are still empty after fallback (or if fallback wasn't needed)
            final_answer = f"I couldn't find any {data_type_context.lower()} matching your specific criteria (Buyer ID: {extracted_buyer_id})."
            if chosen_function_name == "dbo.t2dFunc_GetBuyerSaleOrderDetails":
                 final_answer += " Note: Sales order data is limited to the last 3 months."
        elif execution_error:
             # If the final execution attempt resulted in an error
             final_answer = f"I encountered a database error trying to retrieve the {data_type_context.lower()}. Error: {execution_error}"
        else:
            # Process the results (from Attempt 1 or Fallback Attempt 2)
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

            data_processing_chain = data_processing_prompt_template | llm | StrOutputParser()
            final_answer = data_processing_chain.invoke({
                "db_results": results_json_str,
                "question": request.user_query,
                "data_type": data_type_context
            })
            logger.info(f"LLM processed answer: {final_answer}")

        # == Step 4: Return successful response ==
        # Return the SQL that was *actually executed* last (or attempted last if error)
        return QueryResponse(query=sql_to_execute, answer=final_answer, error=None)

    # == Error Handling for overall process ==
    except HTTPException as http_ex:
        # Re-raise specific HTTP exceptions
        raise http_ex
    except Exception as e:
        # Catch-all for other unexpected errors
        logger.error(f"An unexpected error occurred in the query endpoint: {e}", exc_info=True)
        return QueryResponse(query=sql_to_execute, answer=None, error=f"An unexpected server error occurred: {e}")


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