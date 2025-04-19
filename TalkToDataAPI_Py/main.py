import os
import vanna as vn
from vanna.openai import OpenAI_Chat
from vanna.chromadb import ChromaDB_VectorStore
from openai import AzureOpenAI
import pyodbc # Import the driver
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pydantic Models ---
class QueryRequest(BaseModel):
    user_query: str

class QueryResponse(BaseModel):
    query: str | None # Generated SQL query
    data: list[dict] # Results from the database
    error: str | None = None # Optional error message

# --- Vanna Setup using Custom Class ---
class VannaAzureChroma(ChromaDB_VectorStore, OpenAI_Chat):
    def __init__(self, config=None):
        # Default path for ChromaDB local storage: './chroma'
        ChromaDB_VectorStore.__init__(self, config=config)

        # Load Azure creds specifically for the OpenAI client
        load_dotenv()
        azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_deployment_id = os.getenv("AZURE_OPENAI_DEPLOYMENT_ID")
        azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01") # Example, adjust if needed

        if not all([azure_api_key, azure_endpoint, azure_deployment_id]):
             raise ValueError("Missing Azure OpenAI credentials in .env for AzureOpenAI client")

        # Initialize the AzureOpenAI client
        azure_client = AzureOpenAI(
            api_key=azure_api_key,
            azure_endpoint=azure_endpoint,
            azure_deployment=azure_deployment_id,
            api_version=azure_api_version,
        )

        # Pass the initialized Azure client to OpenAI_Chat
        if config is None:
             config = {}
        config['model'] = azure_deployment_id # Tell Vanna which deployment to use

        OpenAI_Chat.__init__(self, client=azure_client, config=config)

# Instantiate Vanna globally for the API using the custom class
# Ensure the model deployment ID is passed in config
try:
    logger.info("Initializing Vanna instance for API...")
    vn_instance = VannaAzureChroma(config={'model': os.getenv("AZURE_OPENAI_DEPLOYMENT_ID")})
    logger.info("Vanna instance initialized successfully.")
    # Attempt to connect to DB on startup to verify connection string
    conn_string_check = os.getenv("DB_CONNECTION_STRING")
    if conn_string_check:
        logger.info("Attempting database connection check...")
        # Note: Vanna's connect methods often handle this, but we can do a direct check too
        try:
            # Connecting the global instance
            vn_instance.connect_to_mssql(odbc_conn_str=conn_string_check)
            logger.info("Database connection check successful.")
        except Exception as db_init_err:
            logger.warning(f"Initial database connection check failed: {db_init_err}. Endpoints might fail.")
    else:
        logger.warning("DB_CONNECTION_STRING not found. Database operations will fail.")

except ValueError as e:
    logger.critical(f"Failed to initialize Vanna on startup: {e}")
    vn_instance = None # Ensure instance is None if init fails
except Exception as e:
    logger.critical(f"Unexpected error initializing Vanna: {e}")
    vn_instance = None
# --- End Vanna Setup ---


# --- Database Connection ---
def get_db_connection():
    """Creates and returns a database connection."""
    load_dotenv() # Ensure env vars are loaded
    connection_string = os.getenv("DB_CONNECTION_STRING")
    if not connection_string:
         logger.error("DB_CONNECTION_STRING not found in environment variables.")
         raise HTTPException(status_code=500, detail="Database configuration error.")
    try:
        # Using trusted_connection='no' usually needed with Uid/Pwd
        conn = pyodbc.connect(connection_string, autocommit=False) # Start with autocommit false for safety
        logger.info("Database connection established.")
        return conn
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logger.error(f"Database connection error. SQLSTATE: {sqlstate}. Message: {ex}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {ex}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during DB connection: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected DB connection error: {e}")


# --- FastAPI App ---
app = FastAPI(
    title="TalkToData API (Vanna+FastAPI+Azure+iTVF)", # Updated title
    description="API using Vanna with Azure OpenAI and local ChromaDB to query iTVFs.", # Updated description
)

# CORS Configuration
origins = [
    "http://localhost:3000", # Allow your React frontend
    # Add other origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)

# --- API Endpoints ---
@app.post("/api/query", response_model=QueryResponse)
async def query_database(request: QueryRequest):
    """
    Receives a natural language query, generates SQL using Vanna (targeting iTVFs),
    executes it against the database, and returns the results.
    """
    logger.info(f"Received query: '{request.user_query}'")
    sql_query = None
    results = []

    if vn_instance is None:
        logger.error("Vanna instance is not initialized.")
        raise HTTPException(status_code=503, detail="Query service is unavailable due to initialization error.")

    try:
        # Step 1: Generate SQL using Vanna instance
        logger.info("Generating SQL query with Vanna...")
        # Optional: Pass additional context like buyer_id if needed by Vanna/LLM
        # Example: context = {"buyer_id": request.buyer_id} if request.buyer_id else None
        # sql_query = vn_instance.generate_sql(question=request.user_query, context=context)
        sql_query = vn_instance.generate_sql(question=request.user_query) # Using the globally initialized vn_instance

        if not sql_query:
             logger.warning("Vanna did not generate a SQL query.")
             raise HTTPException(status_code=400, detail="Could not generate SQL query for the question.")

        logger.info(f"Generated SQL: {sql_query}")

        # Basic safety check (Keep as is)
        if not sql_query.strip().upper().startswith("SELECT"):
             logger.error(f"Generated query is not a SELECT statement: {sql_query}")
             raise HTTPException(status_code=400, detail="Generated query is not a valid SELECT statement.")

        # Step 2: Execute SQL Query
        conn = None # Ensure conn is defined before try block
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            logger.info("Executing generated SQL query...")
            cursor.execute(sql_query)

            # Fetch column names
            columns = [column[0] for column in cursor.description]
            logger.info(f"Query executed successfully. Columns: {columns}")

            # Fetch rows and format as list of dictionaries
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))

            logger.info(f"Fetched {len(results)} rows.")
            cursor.close()
            conn.commit() # Commit if the query was successful (though SELECTs don't usually need commit)

        except pyodbc.Error as db_ex:
            sqlstate = db_ex.args[0]
            error_message = f"Database execution error. SQLSTATE: {sqlstate}. Message: {db_ex}"
            logger.error(error_message)
            # Attempt to rollback on error
            if conn:
                try:
                    conn.rollback()
                except Exception as rollback_ex:
                    logger.error(f"Failed to rollback transaction: {rollback_ex}")
            # Return error detail including the failed SQL
            raise HTTPException(status_code=400, detail=f"{error_message}. Failed SQL: {sql_query}")
        except Exception as e:
             logger.error(f"Unexpected error during query execution: {e}")
             if conn:
                 try:
                     conn.rollback()
                 except Exception as rollback_ex:
                     logger.error(f"Failed to rollback transaction: {rollback_ex}")
             raise HTTPException(status_code=500, detail=f"Unexpected error during query execution: {e}")
        finally:
            if conn:
                conn.close()
                logger.info("Database connection closed.")

        # Step 3: Return successful response
        return QueryResponse(query=sql_query, data=results)

    except HTTPException as http_ex:
        # Re-raise HTTPExceptions directly
        raise http_ex
    except Exception as e:
        # Catch-all for other unexpected errors (e.g., during Vanna generation)
        logger.error(f"An unexpected error occurred in the query endpoint: {e}")
        # Return the error message in the response body for debugging
        return QueryResponse(query=sql_query, data=[], error=f"An unexpected error occurred: {e}")


@app.get("/health", summary="Health Check")
async def health_check():
    # Add a check for Vanna initialization
    status = "ok" if vn_instance is not None else "error: vanna not initialized"
    return {"status": status}

# --- Run Server (for local development) ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server with uvicorn...")
    # Ensure Vanna is initialized before running, or handle gracefully
    if vn_instance is None:
        logger.critical("Vanna instance failed to initialize. API endpoints will not work.")
        # Decide whether to exit or run with limited functionality
        # exit(1) # Option to exit if Vanna is critical
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
