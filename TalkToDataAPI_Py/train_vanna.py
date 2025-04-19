import os
import vanna as vn
# Import necessary classes
from vanna.openai import OpenAI_Chat
from vanna.chromadb import ChromaDB_VectorStore
from openai import AzureOpenAI # Import AzureOpenAI client
from dotenv import load_dotenv

# --- Configuration ---

# --- iTVF Definitions ---
# Replace with the actual CREATE FUNCTION ... RETURNS TABLE statements
# for the iTVFs Vanna should be aware of.
# Example:
# FUNCTION_DEFINITIONS = [
#     """
#     CREATE FUNCTION fn_GetSalesByDateRange (@StartDate DATE, @EndDate DATE)
#     RETURNS TABLE
#     AS
#     RETURN
#     (
#         SELECT SalesYear, SalesMonth, TotalSales
#         FROM vw_MonthlySales -- Or query base tables directly
#         WHERE CAST(STR(SalesYear) + '-' + STR(SalesMonth) + '-01' AS DATE) BETWEEN @StartDate AND @EndDate
#     );
#     """,
#     """
#     CREATE FUNCTION fn_GetProductSalesByName (@ProductName NVARCHAR(100))
#     RETURNS TABLE
#     AS
#     RETURN
#     (
#         SELECT p.ProductName, oi.Quantity, oi.UnitPrice, oi.Quantity * oi.UnitPrice AS LineTotal
#         FROM SalesOrderItem oi
#         JOIN Products p ON oi.ProductID = p.ProductID
#         WHERE p.ProductName LIKE @ProductName -- Example using LIKE
#           AND oi.Deleted = 0
#           AND p.Deleted = 0
#     );
#     """
# ]

# *** ACTION REQUIRED: Add the actual iTVF definitions here ***
FUNCTION_DEFINITIONS = [
    """
 create FUNCTION [dbo].[t2dFunc_GetBuyerProductDetails]
(
    @buyerId INT
)
RETURNS TABLE
AS
RETURN
(
   SELECT  Products.ProductId, Products.Code, Products.Description, Products.InventoryCode,  Products.USABrandName, Products.IndianBrandName, Products.IdentityID, Products.GenericName, Products.ManufacturerId, 
             Products.MfgApproval, Products.Strength, Products.DosageID, Products.UnitID, Products.PackSize, Products.BoxSize, Products.Multiplier, Products.PackWeight, Products.BoxWeight, Products.Presentation, Products.CountryName, Products.GroupID, Products.PriceCodeID, 
             Products.Labelling, Products.ProductListed, Products.PriceUpdateComment, Products.PurchasersComment, Products.PharmacyCode, Products.PharmacyMultiplier, Products.ETADate, Products.ReorderQuantity, Products.Deleted, Products.isActive, Products.OldId, 
             Products.HumanVat, Products.SourceCategory, Products.ContentType, Products.ProductNature, Products.MarketedById, Products.JapaneseDescription, 
             [Group].Name, ProductMonograph.Monograph4, ProductMonograph.MonographDesc, Buyer.BuyerId, Buyer.Code AS BuyerCode, Buyer.Name AS BuyerName, Affiliate.AffiliateId, Affiliate.BuyerId AS Buyer_Id, 
             Affiliate.Code AS Affilicate_Code, Affiliate.Name AS AffiliateName, [Identity].Name AS ProductIdentity, ProductPrice.Rate, ProductPrice.LastUpdateDate
FROM   Affiliate INNER JOIN
             PriceType INNER JOIN
             Buyer ON PriceType.PriceTypeId = Buyer.PriceTypeId ON Affiliate.BuyerId = Buyer.BuyerId INNER JOIN
             ProductPrice ON PriceType.PriceTypeId = ProductPrice.PriceTypeId INNER JOIN
             ProductMonograph INNER JOIN
             [Identity] INNER JOIN
             Products ON [Identity].IdentityId = Products.IdentityID INNER JOIN
             PriceCode ON Products.PriceCodeID = PriceCode.PriceCodeID ON ProductMonograph.ProductId = Products.ProductId INNER JOIN
             [Group] ON Products.GroupID = [Group].GroupId ON ProductPrice.ProductID = Products.ProductId
			 where PRODUCTs.isblocked=0 and products.isactive=1
			 and Buyer.BuyerId = @buyerId
);
    """
    # Add more CREATE FUNCTION statements as needed
]

# --- Optional but Recommended: Add Documentation ---
# Describe the iTVFs and their parameters.
# Example:
# DOCUMENTATION = [
#     "fn_GetSalesByDateRange returns monthly sales totals between a start and end date. Parameters: @StartDate DATE, @EndDate DATE.",
#     "fn_GetProductSalesByName returns individual sales line items for products matching a name pattern. Parameter: @ProductName NVARCHAR(100) (supports wildcards like '%').",
# ]

# *** ACTION REQUIRED: Add documentation for your iTVFs here ***
DOCUMENTATION = [
    "t2dFunc_GetBuyerProductDetails returns details about product, its price/rate for the buyer and ites affiliates. Parameter: @buyerId INT",
]

# --- Optional but Recommended: Add Sample Questions/SQL ---
# The SQL should now be SELECT statements querying the iTVFs.
# Example:
# QUESTIONS = [
#     {'question': 'Show me sales between January 2023 and March 2023',
#      'sql': "SELECT SalesYear, SalesMonth, TotalSales FROM fn_GetSalesByDateRange( N'2023-01-01', N'2023-03-31' );"},
#     {'question': 'What were the sales last quarter?',
#      'sql': "SELECT SalesYear, SalesMonth, TotalSales FROM fn_GetSalesByDateRange( DATEADD(q, DATEDIFF(q, 0, GETDATE()) - 1, 0), DATEADD(d, -1, DATEADD(q, DATEDIFF(q, 0, GETDATE()), 0)) );"},
#     {'question': 'Find sales details for products containing "Widget"',
#      'sql': "SELECT ProductName, Quantity, UnitPrice, LineTotal FROM fn_GetProductSalesByName( N'%Widget%' );"},
# ]

# *** ACTION REQUIRED: Add sample questions and their corresponding SQL queries targeting your iTVFs ***
QUESTIONS = [
     {'question': 'Show me price details for product ZELDOX (NE) 60mg 56 Cap for buyer 10', # Example with buyerId
      'sql': "SELECT * FROM t2dFunc_GetBuyerProductDetails(10);"},
      {'question': 'Please help regarding the Product number for Elipran 40mg for buyer 25', # Example with buyerId
      'sql': "SELECT * FROM t2dFunc_GetBuyerProductDetails(25);"},
      # Add more examples covering different scenarios and buyer IDs if possible
]
# --- End Configuration ---


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
        # You might need api_version depending on your openai lib version / azure setup
        # Find your Azure OpenAI API version e.g. in the Azure Portal
        azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01") # Example, adjust if needed

        if not all([azure_api_key, azure_endpoint, azure_deployment_id]):
             raise ValueError("Missing Azure OpenAI credentials in .env for AzureOpenAI client")

        # Initialize the AzureOpenAI client from the openai library
        azure_client = AzureOpenAI(
            api_key=azure_api_key,
            azure_endpoint=azure_endpoint,
            azure_deployment=azure_deployment_id,
            api_version=azure_api_version,
        )

        # Pass the initialized Azure client to OpenAI_Chat
        # Also pass the deployment name as the 'model' in config for Vanna's internal use
        if config is None:
             config = {}
        config['model'] = azure_deployment_id # Tell Vanna which deployment to use

        OpenAI_Chat.__init__(self, client=azure_client, config=config)

# Instantiate Vanna using the custom class
# vn_instance = VannaAzureChroma() # config can be passed if needed, e.g., {'model': 'deployment_id'}
# --- End Vanna Setup ---


def train_model(vn):
    print("Loading database environment variables...")
    load_dotenv()
    connection_string = os.getenv("DB_CONNECTION_STRING")

    if not connection_string:
        print("Error: Missing DB_CONNECTION_STRING environment variable in .env file.")
        return

    try:
        print(f"Connecting to database...")
        vn.connect_to_mssql(odbc_conn_str=connection_string)
        print("Database connection successful.")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        print("Please ensure the connection string in .env is correct and the necessary ODBC driver is installed.")
        return

    # --- Training ---
    print("Starting Vanna training...")

    existing_training_data = vn.get_training_data()
    if existing_training_data is not None:
        print(f"Found {len(existing_training_data)} existing training data entries.")
        print("Recommendation: Manually manage training data removal if needed for finer control.")


    # Train on DDL (iTVF Definitions)
    print(f"Training on {len(FUNCTION_DEFINITIONS)} FUNCTION definitions...")
    for ddl in FUNCTION_DEFINITIONS:
        ddl_cleaned = ddl.strip()
        if ddl_cleaned and "CREATE FUNCTION" in ddl_cleaned.upper() and not ddl_cleaned.startswith("--"):
             try:
                print(f"Adding DDL (Function):\n{ddl_cleaned[:150]}...")
                vn.train(ddl=ddl_cleaned)
             except Exception as e:
                 print(f"Error training on DDL (Function): {e}\nDDL: {ddl_cleaned[:200]}...")
        else:
            print("Skipping empty, commented-out, or invalid DDL definition.")
    print("DDL (Function) training complete.")

    # Train on Documentation
    if DOCUMENTATION:
        print(f"Training on {len(DOCUMENTATION)} documentation entries...")
        for doc in DOCUMENTATION:
            if doc.strip():
                try:
                    vn.train(documentation=doc.strip())
                except Exception as e:
                    print(f"Error training on documentation: {e}\nDoc: {doc[:100]}...")
        print("Documentation training complete.")
    else:
        print("No documentation provided for training.")

    # Train on Question-SQL pairs
    if QUESTIONS:
        print(f"Training on {len(QUESTIONS)} Question/SQL pairs...")
        for pair in QUESTIONS:
            question = pair.get('question', '').strip()
            sql = pair.get('sql', '').strip()
            # Adjusted check for robustness
            if question and sql and sql.upper().startswith("SELECT") and ("FROM T2DFUNC_" in sql.upper() or "FROM FN_" in sql.upper()):
                try:
                    vn.train(question=question, sql=sql)
                except Exception as e:
                    print(f"Error training on Q/SQL pair: {e}\nQ: {question}\nSQL: {sql[:100]}...")
            else:
                print(f"Skipping invalid or non-function Q/SQL pair: {pair}")
        print("Question/SQL training complete.")
    else:
        print("No Question/SQL pairs provided for training.")

    print("--- Vanna Training Finished ---")

if __name__ == "__main__":
    try:
        # Instantiate Vanna using the custom class
        # Pass config if needed, ensuring 'model' key is set to your Azure deployment ID
        config = {'model': os.getenv("AZURE_OPENAI_DEPLOYMENT_ID")}
        vn_instance = VannaAzureChroma(config=config)
        train_model(vn_instance) # Pass the instance to the training function
    except ValueError as e:
        print(f"Initialization Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
