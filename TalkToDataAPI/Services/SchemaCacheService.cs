using Microsoft.Extensions.Caching.Memory;
using Microsoft.Data.SqlClient;
using Microsoft.Extensions.Configuration;
using System;
using System.Collections.Generic;
using System.Data.SqlClient;
using System.Threading.Tasks;

namespace TalkToDataAPI.Services
{
    public class SchemaCacheService
    {
        private readonly IMemoryCache _cache;
        private readonly IConfiguration _configuration;
        private readonly string _connectionString;
        private const string SchemaCacheKey = "DatabaseSchema";


        public SchemaCacheService(IMemoryCache cache, IConfiguration configuration)
        {
            _cache = cache;
            _configuration = configuration;
            _connectionString = _configuration.GetConnectionString("AzureSQL");
        }

        public async Task InitializeSchemaCache()
        {
            if (!_cache.TryGetValue(SchemaCacheKey, out _))
            {
                await RefreshSchemaCache();
            }
        }

        public async Task<string> GetSchema()
        {
            if (!_cache.TryGetValue(SchemaCacheKey, out string schema))
            {
                await RefreshSchemaCache();
                _cache.TryGetValue(SchemaCacheKey, out schema);
            }
            return schema;
        }

        public async Task RefreshSchemaCache()
        {
            var schema = await FetchDatabaseSchema();
            _cache.Set(SchemaCacheKey, schema);
        }



        private async Task<string> FetchDatabaseSchema()
        {
            var schemaInfo = new List<string>();

            using (SqlConnection conn = new SqlConnection(_connectionString))
            {
                await conn.OpenAsync();
                string query = @"
                    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    ORDER BY TABLE_NAME, ORDINAL_POSITION;
                ";

                using (SqlCommand cmd = new SqlCommand(query, conn))
                {
                    using (SqlDataReader reader = await cmd.ExecuteReaderAsync())
                    {
                        string currentTable = "";
                        while (await reader.ReadAsync())
                        {
                            string table = reader["TABLE_NAME"].ToString();
                            string column = reader["COLUMN_NAME"].ToString();
                            string type = reader["DATA_TYPE"].ToString();

                            if (currentTable != table)
                            {
                                schemaInfo.Add($"\nTable: {table}");
                                currentTable = table;
                            }

                            schemaInfo.Add($"  - {column} ({type})");
                        }
                    }
                }
            }
            return string.Join("\n", schemaInfo);
        }

        public async Task<bool> HasSchemaChanged()
        {
            using (SqlConnection conn = new SqlConnection(_connectionString))
            {
                await conn.OpenAsync();
                string query = "SELECT MAX(ChangeTime) FROM SchemaChangeLog";

                using (SqlCommand cmd = new SqlCommand(query, conn))
                {
                    var lastChange = await cmd.ExecuteScalarAsync();
                    return lastChange != null && Convert.ToDateTime(lastChange) > DateTime.UtcNow.AddMinutes(-5);
                }
            }
        }

        private Dictionary<string, string> GetKeywordTableMappings()
        {
            return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        { "sales", "SalesOrder" },
         { "sale", "SalesOrder" },
          { "order", "SalesOrder" },
           { "orders", "SalesOrder" },
         //{ "sales", "SalesOrderItem" },
          //{ "sales", "Products" },
        { "revenue", "Orders" },
        { "customers", "Buyer" },
          { "Buyer", "Buyer" },
        { "products", "Products" },
         { "product", "Products" },
        { "employees", "User" },

        { "total sales", "SalesOrder" },
        { "purchase", "GoodsReceiptNote" },
        { "inventory", "GoodsReceiptNote" },
        { "stock", "GoodsReceiptNote" },
        { "transactions", "SalesOrder" }
    };
        }
        public List<string> ExtractRelevantTables(string userQuery)
        {
            var mappings = GetKeywordTableMappings();
            var matchedTables = new HashSet<string>();

            foreach (var keyword in mappings.Keys)
            {
                if (userQuery.Contains(keyword, StringComparison.OrdinalIgnoreCase))
                {
                    matchedTables.Add(mappings[keyword]);
                }
            }

            return matchedTables.ToList();
        }

        //public List<string> ExtractRelevantTables(string userQuery)
        //{
        //    var mappings = GetKeywordTableMappings();
        //    var matchedTables = new HashSet<string>();

        //    foreach (var keyword in mappings.Keys)
        //    {
        //        if (userQuery.Contains(keyword, StringComparison.OrdinalIgnoreCase))
        //        {
        //            foreach (var table in mappings[keyword])  // Handle multiple tables per keyword
        //            {
        //                matchedTables.Add(table);
        //            }
        //        }
        //    }

        //    return matchedTables.ToList();
        //}

        public async Task<string> GetRelevantSchema(List<string> relevantTables)
        {
            if (!_cache.TryGetValue(SchemaCacheKey, out string fullSchema))
            {
                await RefreshSchemaCache();
                _cache.TryGetValue(SchemaCacheKey, out fullSchema);
            }

            var schemaLines = fullSchema.Split('\n');
            var filteredSchema = new List<string>();

            bool includeTable = false;

            foreach (var line in schemaLines)
            {
                if (line.StartsWith("Table:"))
                {
                    includeTable = relevantTables.Any(table => line.Contains(table, StringComparison.OrdinalIgnoreCase));
                }

                if (includeTable)
                {
                    filteredSchema.Add(line);
                }
            }

            return string.Join("\n", filteredSchema);
        }

    //    private Dictionary<string, List<string>> GetKeywordTableMappings()
    //    {
    //        return new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase)
    //{
    //    { "actionid", new List<string> { "ActionsMaster" } },
    //    { "actionname", new List<string> { "ActionsMaster", "ActivityLog" } },
    //    { "deleted", new List<string> { "IssueShipmentDetail", "DecideOrderStatus", "Buyer", "Identity", "WinServicePendingIssue", "WarehouseProductStock", "City", "SalesOrderItem", "Bin", "PaymentDetail", "Currency", "POCharge", "GoodsReceiptNoteChargeTemp", "Category", "Products", "GoodsReceiptNoteCharge", "Affiliate", "State", "PurchaseInvoiceItem", "ReturnShippingAddress", "Warehouse", "CreditNoteItem", "GoodsReturn", "ErrorLog", "SaleInvoiceCharge", "CurrencyRate", "DecideOrderShippingType_GWS", "Terms", "Payment", "SaleInvoiceItem", "DCompany", "Consignee", "B2BInvoiceConfiguration", "B2BRetailPacker", "LongExpiryStockForIssue", "OrderStatus", "Manufacturer", "SGPIssueShipmentDetail", "Issue", "User", "SalesOrder", "ActionsMaster", "IssueItemTemp", "OrderStatusReason", "IssueBoxweight", "UserWarehouse", "MarketedBy", "POBillingDetails", "Batch", "POTermsTemp", "PurchaseOrderItem", "POShippingDetails", "POTerms", "CreditNote", "StockInAlert", "SupplierWarehouse", "Dosage", "ProductPriceBackUp", "SaleOrderCharge", "DHLIssueShipmentDetail", "BatchDetail", "Group", "IssueText", "GoodsReceiptNoteItem", "B2BRetailShipper", "ProductMonograph", "ClientInvoiceItem", "DebitNoteItem", "Patient", "UserBuyer", "PurchaseOrderItemTemp", "Alert", "B2BInvoiceItem", "CountryVariation", "Charge", "DecideOrderStatus_GWS", "IssueItem", "ProductBin", "PurchaseInvoice", "UserSupplier", "ARC_REGIssueShipmentDetail", "DummySaleInvoice", "Supplier", "B2BRetailExporter", "B2BInvoice", "Unit", "GoodsReceiptNoteItemTemp", "REGIssueShipmentDetail", "GoodsReturnItem", "POChargeTemp", "PriceType", "B2BInvoiceConfiguration_Backup17AUG21", "DHLItemNumberStructure", "PurchaseInvoiceCharge", "GoodsReceiptNote", "Company", "SGPIssueShipmentDetailCN22", "B2BRetailConsignee", "SGPItemNumberStructure", "PatientDocument", "BuyerWarehouse", "PriceCode", "Margin", "ItemNumberStructure", "ShippingType", "ClientInvoice", "DebitNote", "Menu", "BatchDebitNote", "ShortExpiryStockForIssue", "ProductPrice", "B2BRetailBuyer", "InvoicingCompany", "DHLCountry", "Module", "SaleOrderItemWholesaleTemp", "Country", "SaleInvoice", "UserShippingType", "PurchaseOrder", "SupplierBuyer" } },
    //    { "activitylogid", new List<string> { "ActivityLog" } },
    //    { "userid", new List<string> { "AuditLog", "UserShippingType", "User", "UserId", "UserBuyer", "UserPasswordHistory", "UserWarehouse", "UserSupplier", "GoodsReceiptNoteItemTemp", "ActivityLog" } },
    //    { "ipaddress", new List<string> { "ActivityLog" } },
    //    { "activitydate", new List<string> { "ActivityLog" } },
    //    { "timestamp", new List<string> { "IssueShipmentDetail", "CreditNote", "StockInAlert", "CurrencyRate", "PurchaseOrder", "ShipRegisterForClient", "AuditLog", "ProductPriceBackUp", "JMCInvoice", "DHLIssueShipmentDetail", "WinServicePendingIssue", "GoodsReceiptNote", "Payment", "BackOrderForClientLogin", "ActivityLog", "SalesOrderItem", "SGPIssueShipmentDetailCN22", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "TrnBoxDetails", "LongExpiryStockForIssue", "PurchaseOrderItemTemp", "SGPIssueShipmentDetail", "InventoryDetails", "Products", "Issue", "JobScheduleCriteria", "ClientInvoice", "DebitNote", "IssueItem", "IssueItemTemp", "SalesOrder", "UserPasswordHistory", "GSSImportTesting", "IssueBatchReport", "ARC_REGIssueShipmentDetail", "PurchaseInvoice", "BatchDebitNote", "DummySaleInvoice", "GoodsReturn", "ShortExpiryStockForIssue", "ProductPrice", "OrderServiceTemp", "Batch", "SaleOrderItemWholesaleTemp", "ErrorLog", "IssueReport_ws", "B2BInvoice", "SaleInvoice", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "REGIssueShipmentDetail" } },
    //    { "time", new List<string> { "IssueShipmentDetail", "CreditNote", "StockInAlert", "CurrencyRate", "PurchaseOrder", "ShipRegisterForClient", "AuditLog", "ProductPriceBackUp", "JMCInvoice", "DHLIssueShipmentDetail", "WinServicePendingIssue", "GoodsReceiptNote", "Payment", "BackOrderForClientLogin", "ActivityLog", "SalesOrderItem", "SGPIssueShipmentDetailCN22", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "TrnBoxDetails", "LongExpiryStockForIssue", "PurchaseOrderItemTemp", "SGPIssueShipmentDetail", "InventoryDetails", "Products", "Issue", "JobScheduleCriteria", "ClientInvoice", "DebitNote", "IssueItem", "IssueItemTemp", "SalesOrder", "UserPasswordHistory", "GSSImportTesting", "IssueBatchReport", "ARC_REGIssueShipmentDetail", "PurchaseInvoice", "BatchDebitNote", "DummySaleInvoice", "GoodsReturn", "ShortExpiryStockForIssue", "ProductPrice", "OrderServiceTemp", "Batch", "SaleOrderItemWholesaleTemp", "ErrorLog", "IssueReport_ws", "B2BInvoice", "SaleInvoice", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "REGIssueShipmentDetail" } },
    //    { "machinename", new List<string> { "ActivityLog" } },
    //    { "moduleid", new List<string> { "Module", "ActivityLog", "ModuleId" } },
    //    { "detail", new List<string> { "ActivityLog" } },
    //    { "description", new List<string> { "TransactionType", "SaleOrderItemRetailTemp", "Products", "IssueItemTemp", "Terms", "Unit", "ActivityLog" } },
    //    { "source", new List<string> { "ActivityLog" } },
    //    { "affiliateid", new List<string> { "JMCInvoice", "Affiliate", "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "buyerid", new List<string> { "CreditNote", "ShipRegisterForClient", "DecideOrderStatus", "Buyer", "DecideOrderShippingType_GWS", "JMCInvoice", "Payment", "BackOrderForClientLogin", "Consignee", "UserBuyer", "LongExpiryStockForIssue", "BuyerWarehouse", "Issue", "Affiliate", "DecideOrderStatus_GWS", "BuyerId", "ClientInvoice", "SalesOrder", "BatchDebitNote", "DummySaleInvoice", "ShortExpiryStockForIssue", "B2BRetailBuyer", "SaleInvoice", "BuyerShippingTypeFee", "SupplierBuyer" } },
    //    { "code", new List<string> { "B2BRetailBuyer", "Consignee", "Products", "B2BRetailShipper", "Supplier", "Affiliate", "B2BRetailExporter", "Buyer", "Warehouse", "B2BRetailPacker", "SheetLocation", "Company", "B2BRetailConsignee" } },
    //    { "name", new List<string> { "PriceType", "Dosage", "Buyer", "Identity", "Company", "B2BRetailConsignee", "Bin", "Consignee", "DCompany", "Group", "PaymentType", "B2BRetailShipper", "B2BRetailPacker", "Manufacturer", "PriceCode", "Category", "BusinessType", "Charge", "Affiliate", "OrderStatusReason", "ReturnShippingAddress", "Warehouse", "B2BRetailBuyer", "MarketedBy", "InvoicingCompany", "Supplier", "Bank", "Country", "B2BRetailExporter" } },
    //    { "street", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Affiliate", "Buyer", "Patient", "GSSImportTesting", "ReturnShippingAddress" } },
    //    { "city", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Affiliate", "Buyer", "Patient", "GSSImportTesting", "ReturnShippingAddress", "Company", "Warehouse" } },
    //    { "state", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Affiliate", "Buyer", "Patient", "GSSImportTesting", "ReturnShippingAddress", "Company", "Warehouse" } },
    //    { "zip", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Affiliate", "Buyer", "Patient", "GSSImportTesting", "ReturnShippingAddress", "Company", "Warehouse" } },
    //    { "country", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Affiliate", "Buyer", "Patient", "GSSImportTesting", "ReturnShippingAddress", "Company", "Warehouse" } },
    //    { "phone", new List<string> { "Affiliate" } },
    //    { "email", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Affiliate", "Buyer", "Company", "Warehouse" } },
    //    { "reveivepricechangealert", new List<string> { "Affiliate" } },
    //    { "cost", new List<string> { "POChargeTemp", "CreditNote", "PriceType", "SaleInvoiceCharge", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "JMCInvoiceItem", "PurchaseOrder", "SaleOrderItemTemp", "ProductPriceBackUp", "Buyer", "JMCInvoice", "SaleOrderCharge", "GoodsReceiptNote", "Payment", "SaleInvoiceItem", "SalesOrderItem", "JMCClient", "DCompany", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "PaymentDetail", "SaleInvoiceChargeTemp", "InternalInvoiceChargeTemp", "SaleInvoiceItemTemp", "DebitNoteItem", "Patient", "POCharge", "GoodsReceiptNoteChargeTemp", "PriceCode", "InventoryDetails", "Products", "GoodsReceiptNoteCharge", "Affiliate", "SaleOrderChargeTemp", "DebitNote", "SalesOrder", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GSSImportTesting", "PurchaseInvoice", "BatchDebitNote", "DummySaleInvoice", "GoodsReturn", "CreditNoteItem", "ProductPrice", "InvoicingCompany", "Supplier", "SaleInvoice", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "rate", new List<string> { "PriceType", "JMCInvoiceItem", "SaleOrderItemTemp", "ProductPriceBackUp", "Buyer", "GoodsReceiptNote", "SaleInvoiceItem", "SalesOrderItem", "JMCClient", "DCompany", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "SaleInvoiceItemTemp", "DebitNoteItem", "PurchaseOrderItemTemp", "PriceCode", "InventoryDetails", "Products", "Charge", "Affiliate", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "DummySaleInvoice", "CreditNoteItem", "ProductPrice", "InvoicingCompany", "SaleOrderItemWholesaleTemp", "Supplier", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "pricelistalertemail", new List<string> { "Affiliate", "Buyer" } },
    //    { "reveivestockinalert", new List<string> { "Affiliate" } },
    //    { "inventory", new List<string> { "StockInAlert", "GoodsReceiptNoteItem", "InventoryDetails", "Affiliate", "Buyer", "WinServicePendingIssue", "DebitNoteItem", "GoodsReceiptNote", "WarehouseProductStock", "GoodsReceiptNoteItemTemp", "CreditNoteItem" } },
    //    { "stockinalertemail", new List<string> { "Affiliate", "Buyer" } },
    //    { "website", new List<string> { "Affiliate" } },
    //    { "rxlabelheader", new List<string> { "Affiliate" } },
    //    { "pharmacyslipfooter", new List<string> { "Affiliate" } },
    //    { "patientdocumentreq", new List<string> { "Affiliate" } },
    //    { "authorizatonreq", new List<string> { "Affiliate" } },
    //    { "username", new List<string> { "User", "Affiliate", "ErrorLog", "Buyer" } },
    //    { "password", new List<string> { "Affiliate", "Buyer" } },
    //    { "ticketemailid", new List<string> { "User", "Affiliate", "Buyer" } },
    //    { "issendticketmail", new List<string> { "User", "Affiliate", "Buyer" } },
    //    { "oldid", new List<string> { "PriceType", "CreditNote", "SaleInvoiceCharge", "CurrencyRate", "Dosage", "PurchaseInvoiceCharge", "ProductPriceBackUp", "Buyer", "Identity", "SaleOrderCharge", "Terms", "GoodsReceiptNote", "Payment", "SaleInvoiceItem", "Company", "SalesOrderItem", "Group", "Consignee", "IssueText", "GoodsReceiptNoteItem", "PaymentDetail", "Currency", "DebitNoteItem", "BuyerWarehouse", "Manufacturer", "PriceCode", "TransactionType", "Category", "Products", "BusinessType", "Charge", "Affiliate", "ShippingType", "IssueItem", "DebitNote", "ProductBin", "PurchaseInvoiceItem", "SalesOrder", "IssueBoxweight", "PurchaseInvoice", "Warehouse", "BatchDebitNote", "CreditNoteItem", "GoodsReturn", "ProductPrice", "Supplier", "SaleInvoice", "Unit", "BuyerShippingTypeFee", "PurchaseOrderItem", "PurchaseOrder", "GoodsReturnItem", "POTerms" } },
    //    { "productdescription", new List<string> { "Affiliate" } },
    //    { "item", new List<string> { "ProductStoreLocation", "StockInAlert", "JMCInvoiceItem", "ShipRegisterForClient", "SaleOrderItemTemp", "DecideOrderStatus", "ProductPriceBackUp", "WinServicePendingIssue", "SaleInvoiceItem", "WarehouseProductStock", "BackOrderForClientLogin", "SalesOrderItem", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "ProductMonograph", "SaleInvoiceItemTemp", "DebitNoteItem", "LongExpiryStockForIssue", "PurchaseOrderItemTemp", "InventoryDetails", "Products", "Affiliate", "DecideOrderStatus_GWS", "IssueItem", "ProductBin", "SalesOrder", "IssueItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GSSImportTesting", "DummySaleInvoice", "CreditNoteItem", "ExcludeImportExportProduct", "ProductPrice", "ShortExpiryStockForIssue", "OrderServiceTemp", "SaleOrderItemWholesaleTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "goods", new List<string> { "ProductStoreLocation", "StockInAlert", "JMCInvoiceItem", "ShipRegisterForClient", "SaleOrderItemTemp", "DecideOrderStatus", "ProductPriceBackUp", "WinServicePendingIssue", "SaleInvoiceItem", "WarehouseProductStock", "BackOrderForClientLogin", "SalesOrderItem", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "ProductMonograph", "SaleInvoiceItemTemp", "DebitNoteItem", "LongExpiryStockForIssue", "PurchaseOrderItemTemp", "InventoryDetails", "Products", "Affiliate", "DecideOrderStatus_GWS", "IssueItem", "ProductBin", "SalesOrder", "IssueItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GSSImportTesting", "DummySaleInvoice", "CreditNoteItem", "ExcludeImportExportProduct", "ProductPrice", "ShortExpiryStockForIssue", "OrderServiceTemp", "SaleOrderItemWholesaleTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "isjmc", new List<string> { "Affiliate", "Buyer" } },
    //    { "jmcpricetypeid", new List<string> { "Affiliate" } },
    //    { "jmcshippingfee", new List<string> { "SalesOrder", "Affiliate", "SaleInvoiceItem", "SalesOrderItem" } },
    //    { "jmcdispensingfee", new List<string> { "SalesOrder", "Affiliate", "SaleInvoiceItem", "SalesOrderItem" } },
    //    { "apikey", new List<string> { "Affiliate", "Buyer" } },
    //    { "allowapi", new List<string> { "Affiliate", "Buyer" } },
    //    { "alertid", new List<string> { "Alert" } },
    //    { "alerttype", new List<string> { "Alert" } },
    //    { "alertmessage", new List<string> { "Alert" } },
    //    { "isactive", new List<string> { "Products", "JobScheduleCriteria", "MstB2BBoxTypes", "Buyer", "SGPCountry", "Alert" } },
    //    { "shipmentid", new List<string> { "IssueShipmentDetail", "SGPIssueShipmentDetail", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "delivery", new List<string> { "IssueShipmentDetail", "SGPIssueShipmentDetail", "SalesOrder", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "issueid", new List<string> { "IssueShipmentDetail", "SGPIssueShipmentDetail", "Issue", "IssueId", "SGPIssueShipmentDetailCN22", "IssueReport_ws", "IssueItem", "SGPApiLog", "DHLIssueShipmentDetail", "IssueBoxweight", "BatchDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "B2BInvoiceItem", "DummySaleInvoice" } },
    //    { "deliverynoteno", new List<string> { "IssueShipmentDetail", "SGPIssueShipmentDetailCN22", "DHLIssueShipmentDetail", "TrnBoxDetails", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "B2BInvoiceItem" } },
    //    { "shippingtypeid", new List<string> { "IssueShipmentDetail", "B2BInvoiceConfiguration_Backup17AUG21", "DHLItemNumberStructure", "Buyer", "DecideOrderShippingType_GWS", "DHLIssueShipmentDetail", "SGPIssueShipmentDetailCN22", "B2BRetailConsignee", "IssueText", "B2BRetailShipper", "SGPItemNumberStructure", "B2BInvoiceConfiguration", "B2BRetailPacker", "ItemNumberStructure", "ShippingType", "SalesOrder", "ARC_REGIssueShipmentDetail", "B2BRetailBuyer", "B2BRetailExporter", "UserShippingType", "ShippingTypeId", "BuyerShippingTypeFee", "REGIssueShipmentDetail" } },
    //    { "itemnumber", new List<string> { "IssueShipmentDetail", "REGBoxNumberDetail", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "trackingnumber", new List<string> { "IssueShipmentDetail", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "creationdate", new List<string> { "IssueShipmentDetail", "SGPIssueShipmentDetail", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "deletiondate", new List<string> { "IssueShipmentDetail", "SGPIssueShipmentDetail", "Issue", "IssueItem", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "deletedby", new List<string> { "IssueShipmentDetail", "LongExpiryStockForIssue", "Issue", "B2BInvoice", "ClientInvoiceItem", "IssueItem", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22", "ShortExpiryStockForIssue" } },
    //    { "ishandover", new List<string> { "IssueShipmentDetail", "ARC_REGIssueShipmentDetail", "DHLIssueShipmentDetail", "REGIssueShipmentDetail" } },
    //    { "itemnumberstructureid", new List<string> { "IssueShipmentDetail", "MapCountryTracking", "DHLItemNumberStructure", "MapSGPCountryTracking", "ItemNumberStructure", "SGPItemNumberStructure", "DHLIssueShipmentDetail", "ARC_REGIssueShipmentDetail", "REGIssueShipmentDetail", "SGPIssueShipmentDetailCN22" } },
    //    { "id", new List<string> { "POChargeTemp", "B2BInvoiceConfiguration_Backup17AUG21", "PurchaseInvoiceChargeTemp", "ShipRegisterForClient", "AuditLog", "SaleOrderCharge", "BackOrderForClientLogin", "MstB2BBoxTypes", "SaleInvoiceChargeTemp", "B2BInvoiceConfiguration", "TrnBoxDetails", "POCharge", "REGBoxNumberDetail", "InventoryDetails", "JobScheduleCriteria", "SaleOrderChargeTemp", "IssueItemTemp", "OrderStatusReason", "PurchaseInvoiceItemTemp", "UserPasswordHistory", "CartonMaster", "MapCountryTracking", "MapSGPCountryTracking", "IssueReport_ws", "POTermsTemp", "SheetLocation" } },
    //    { "auditlogid", new List<string> { "AuditLog" } },
    //    { "eventdateutc", new List<string> { "AuditLog" } },
    //    { "eventtype", new List<string> { "SchemaChangeLog", "AuditLog" } },
    //    { "tablename", new List<string> { "AuditLog" } },
    //    { "recordid", new List<string> { "AuditLog" } },
    //    { "columnname", new List<string> { "AuditLog" } },
    //    { "originalvalue", new List<string> { "AuditLog" } },
    //    { "newvalue", new List<string> { "AuditLog" } },
    //    { "autoissuelogid", new List<string> { "AutoIssueErrorLog" } },
    //    { "messgae", new List<string> { "AutoIssueErrorLog" } },
    //    { "invoiceid", new List<string> { "InvoiceId", "B2BInvoice", "ClientInvoiceItem", "ClientInvoice", "B2BInvoiceItem" } },
    //    { "transtext", new List<string> { "CreditNote", "Issue", "IssueReport_ws", "B2BInvoice", "DebitNote", "ClientInvoice", "SaleInvoice", "GoodsReceiptNote", "BatchDebitNote" } },
    //    { "transdate", new List<string> { "CreditNote", "Issue", "IssueReport_ws", "B2BInvoice", "DebitNote", "ClientInvoice", "JMCInvoice", "SaleInvoice", "GoodsReceiptNote", "IssueBatchReport", "BatchDebitNote" } },
    //    { "airwaybillno", new List<string> { "B2BInvoice", "SaleInvoice", "ClientInvoice" } },
    //    { "airwaybilldate", new List<string> { "B2BInvoice", "SaleInvoice", "ClientInvoice" } },
    //    { "customdeclarationref", new List<string> { "B2BInvoice" } },
    //    { "customdeclarationdate", new List<string> { "B2BInvoice" } },
    //    { "createdby", new List<string> { "B2BInvoice", "Issue", "IssueItem", "ClientInvoice" } },
    //    { "warehouseid", new List<string> { "CreditNote", "ProductStoreLocation", "B2BInvoiceConfiguration_Backup17AUG21", "StockInAlert", "SupplierWarehouse", "JMCInvoice", "WinServicePendingIssue", "GoodsReceiptNote", "WarehouseProductStock", "Bin", "IssueText", "B2BInvoiceConfiguration", "BuyerWarehouse", "Issue", "DebitNote", "UserWarehouse", "PurchaseInvoice", "Warehouse", "BatchDebitNote", "DummySaleInvoice", "GoodsReturn", "WarehouseId", "Batch", "SaleInvoice", "B2BInvoice", "PurchaseOrder" } },
    //    { "consigneename", new List<string> { "ClientInvoice", "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "consigneeaddress", new List<string> { "ClientInvoice", "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "buyername", new List<string> { "ClientInvoice", "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration", "IssueReport_ws" } },
    //    { "buyeraddress", new List<string> { "ClientInvoice", "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "packername", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "packeraddress", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "exportername", new List<string> { "ClientInvoice", "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "exporteraddress", new List<string> { "ClientInvoice", "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "shippername", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "shipperaddress", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "clientexportername", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "clientexporteraddress", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "portofloading", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "ClientInvoice", "B2BInvoiceConfiguration", "Warehouse", "B2BRetailConsignee" } },
    //    { "portofdischarge", new List<string> { "Consignee", "B2BInvoiceConfiguration_Backup17AUG21", "B2BRetailShipper", "ClientInvoice", "B2BInvoiceConfiguration", "B2BRetailConsignee" } },
    //    { "finaldestination", new List<string> { "Consignee", "B2BInvoiceConfiguration_Backup17AUG21", "B2BRetailShipper", "ClientInvoice", "B2BInvoiceConfiguration", "B2BRetailConsignee" } },
    //    { "shippingtypename", new List<string> { "B2BInvoiceConfiguration_Backup17AUG21", "B2BInvoiceConfiguration" } },
    //    { "invoiceitemid", new List<string> { "ClientInvoiceItem", "B2BInvoiceItem" } },
    //    { "isuploaded", new List<string> { "B2BInvoiceItem" } },
    //    { "address", new List<string> { "B2BRetailBuyer", "B2BRetailShipper", "B2BRetailExporter", "Warehouse", "B2BRetailPacker", "Company", "B2BRetailConsignee" } },
    //    { "consigneeid", new List<string> { "Consignee", "B2BRetailShipper", "Issue", "SaleInvoice", "SalesOrder", "ConsigneeId", "DummySaleInvoice", "B2BRetailConsignee" } },
    //    { "exporterid", new List<string> { "B2BRetailExporter" } },
    //    { "packerid", new List<string> { "B2BRetailPacker" } },
    //    { "licenseno", new List<string> { "Consignee", "B2BRetailShipper", "Supplier", "Buyer", "Company" } },
    //    { "vatno", new List<string> { "Consignee", "B2BRetailShipper", "Supplier", "Buyer", "Company" } },
    //    { "buyercode", new List<string> { "GSSImportTesting", "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "affiliatecode", new List<string> { "GSSImportTesting", "BackOrderForClientLogin", "ShipRegisterForClient", "IssueReport_ws" } },
    //    { "orderno", new List<string> { "PendingIssues", "BackOrderForClientLogin", "OrderServiceTemp", "ShipRegisterForClient" } },
    //    { "transaction", new List<string> { "MenuNew", "POChargeTemp", "JMCInvoiceItem", "PurchaseOrder", "SaleOrderItemTemp", "ShipRegisterForClient", "DecideOrderStatus", "Buyer", "DecideOrderShippingType_GWS", "SaleOrderCharge", "WinServicePendingIssue", "SaleInvoiceItem", "BatchDetail", "BackOrderForClientLogin", "SalesOrderItem", "SaleOrderItemRetailTemp", "IssueText", "GoodsReceiptNoteItem", "SaleInvoiceItemTemp", "POCharge", "PatientDocument", "OrderStatus", "PurchaseOrderItemTemp", "InventoryDetails", "Products", "Issue", "DecideOrderStatus_GWS", "IssueItem", "SaleOrderChargeTemp", "SalesOrder", "IssueItemTemp", "GSSImportTesting", "Warehouse", "DummySaleInvoice", "OrderServiceTemp", "PendingIssues", "Batch", "SaleOrderItemWholesaleTemp", "IssueReport_ws", "POTermsTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "POTerms" } },
    //    { "purchase", new List<string> { "MenuNew", "POChargeTemp", "JMCInvoiceItem", "PurchaseOrder", "SaleOrderItemTemp", "ShipRegisterForClient", "DecideOrderStatus", "Buyer", "DecideOrderShippingType_GWS", "SaleOrderCharge", "WinServicePendingIssue", "SaleInvoiceItem", "BatchDetail", "BackOrderForClientLogin", "SalesOrderItem", "SaleOrderItemRetailTemp", "IssueText", "GoodsReceiptNoteItem", "SaleInvoiceItemTemp", "POCharge", "PatientDocument", "OrderStatus", "PurchaseOrderItemTemp", "InventoryDetails", "Products", "Issue", "DecideOrderStatus_GWS", "IssueItem", "SaleOrderChargeTemp", "SalesOrder", "IssueItemTemp", "GSSImportTesting", "Warehouse", "DummySaleInvoice", "OrderServiceTemp", "PendingIssues", "Batch", "SaleOrderItemWholesaleTemp", "IssueReport_ws", "POTermsTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "POTerms" } },
    //    { "orderdate", new List<string> { "SalesOrder", "BackOrderForClientLogin", "OrderServiceTemp", "ShipRegisterForClient" } },
    //    { "patientfname", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "patientlname", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "patientstreet", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "patientcity", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "patientstate", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "patientzip", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "patientcountry", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "statusname", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "ordernotes", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "productcode", new List<string> { "SaleOrderItemRetailTemp", "ShipRegisterForClient", "SaleOrderItemWholesaleTemp", "IssueItemTemp", "GSSImportTesting", "BackOrderForClientLogin" } },
    //    { "productname", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "company", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "genericname", new List<string> { "SaleOrderItemRetailTemp", "Products", "SaleOrderItemWholesaleTemp", "ShipRegisterForClient", "IssueItemTemp", "BackOrderForClientLogin" } },
    //    { "usabrandname", new List<string> { "SaleOrderItemRetailTemp", "Products", "SaleOrderItemWholesaleTemp", "ShipRegisterForClient", "IssueItemTemp", "BackOrderForClientLogin" } },
    //    { "identity", new List<string> { "SaleOrderItemWholesaleTemp", "SaleOrderItemRetailTemp", "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "demand", new List<string> { "BackOrderForClientLogin", "ShipRegisterForClient" } },
    //    { "etadate", new List<string> { "SaleOrderItemRetailTemp", "Products", "SaleOrderItemWholesaleTemp", "ShipRegisterForClient", "BackOrderForClientLogin", "SalesOrderItem" } },
    //    { "buyerlineid", new List<string> { "SaleOrderItemRetailTemp", "OrderServiceTemp", "ShipRegisterForClient", "GSSImportTesting", "BackOrderForClientLogin", "SalesOrderItem" } },
    //    { "bankid", new List<string> { "Bank", "BankId", "Payment" } },
    //    { "bankaccounttype", new List<string> { "Bank" } },
    //    { "batchid", new List<string> { "IssueBatchReport", "BatchId", "BatchDetail", "Batch" } },
    //    { "batchnumber", new List<string> { "Batch" } },
    //    { "batchcreationdate", new List<string> { "DummySaleInvoice", "Batch" } },
    //    { "numberoforders", new List<string> { "Batch" } },
    //    { "timeofcreation", new List<string> { "Batch" } },
    //    { "issuecreator", new List<string> { "Batch" } },
    //    { "isprinted", new List<string> { "Batch" } },
    //    { "batchdebitnoteid", new List<string> { "BatchDebitNote" } },
    //    { "transtypeid", new List<string> { "CreditNote", "DebitNote", "BatchDebitNote" } },
    //    { "transno", new List<string> { "CreditNote", "Issue", "IssueReport_ws", "SaleInvoice", "DebitNote", "GoodsReceiptNote", "BatchDebitNote" } },
    //    { "batchno", new List<string> { "GoodsReceiptNoteItem", "ShipRegisterForClient", "IssueReport_ws", "IssueItemTemp", "GoodsReceiptNoteItemTemp", "BatchDebitNote", "DummySaleInvoice" } },
    //    { "currencyid", new List<string> { "PriceType", "CreditNote", "CurrencyRate", "SaleInvoice", "DebitNote", "SalesOrder", "CurrencyId", "Currency", "GoodsReceiptNote", "Payment", "PurchaseInvoice", "PurchaseOrder", "Company", "BatchDebitNote", "GoodsReturn" } },
    //    { "buyerref", new List<string> { "CreditNote", "BatchDebitNote" } },
    //    { "conversionfactor", new List<string> { "CreditNote", "SaleInvoice", "DebitNote", "Payment", "BatchDebitNote", "GoodsReturn" } },
    //    { "totalamount", new List<string> { "CreditNote", "SaleInvoice", "DebitNote", "JMCInvoice", "GoodsReceiptNote", "Payment", "PurchaseInvoice", "PurchaseOrder", "BatchDebitNote", "GoodsReturn" } },
    //    { "total", new List<string> { "POChargeTemp", "CreditNote", "SaleInvoiceCharge", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "JMCInvoiceItem", "PurchaseOrder", "SaleOrderItemTemp", "JMCInvoice", "SaleOrderCharge", "GoodsReceiptNote", "Payment", "SaleInvoiceItem", "SalesOrderItem", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "PaymentDetail", "SaleInvoiceChargeTemp", "InternalInvoiceChargeTemp", "SaleInvoiceItemTemp", "DebitNoteItem", "Patient", "POCharge", "GoodsReceiptNoteChargeTemp", "GoodsReceiptNoteCharge", "SaleOrderChargeTemp", "DebitNote", "SalesOrder", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GSSImportTesting", "PurchaseInvoice", "BatchDebitNote", "DummySaleInvoice", "GoodsReturn", "CreditNoteItem", "SaleInvoice", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "value", new List<string> { "POChargeTemp", "CreditNote", "SaleInvoiceCharge", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "JMCInvoiceItem", "PurchaseOrder", "SaleOrderItemTemp", "JMCInvoice", "SaleOrderCharge", "GoodsReceiptNote", "Payment", "SaleInvoiceItem", "SalesOrderItem", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "PaymentDetail", "SaleInvoiceChargeTemp", "InternalInvoiceChargeTemp", "SaleInvoiceItemTemp", "DebitNoteItem", "Patient", "POCharge", "GoodsReceiptNoteChargeTemp", "GoodsReceiptNoteCharge", "SaleOrderChargeTemp", "DebitNote", "SalesOrder", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GSSImportTesting", "PurchaseInvoice", "BatchDebitNote", "DummySaleInvoice", "GoodsReturn", "CreditNoteItem", "SaleInvoice", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "ctotalamount", new List<string> { "CreditNote", "PurchaseInvoiceCharge", "GoodsReceiptNoteCharge", "SaleInvoice", "DebitNote", "PurchaseInvoiceItem", "GoodsReceiptNote", "BatchDebitNote", "GoodsReturn", "GoodsReceiptNoteChargeTemp" } },
    //    { "isforamount", new List<string> { "CreditNote", "DebitNote", "BatchDebitNote" } },
    //    { "batchdetailid", new List<string> { "BatchDetail" } },
    //    { "salesorderid", new List<string> { "SalesOrderId", "SalesOrder", "IssueItemTemp", "WinServicePendingIssue", "BatchDetail", "PatientDocument", "SalesOrderItem" } },
    //    { "binid", new List<string> { "ProductBin", "Bin", "BinId" } },
    //    { "businesstypeid", new List<string> { "BusinessType", "BusinessTypeId", "Warehouse" } },
    //    { "buyertype", new List<string> { "Buyer" } },
    //    { "pricetypeid", new List<string> { "PriceType", "DCompany", "ProductPrice", "InvoicingCompany", "Supplier", "PriceTypeId", "ProductPriceBackUp", "Buyer", "GoodsReceiptNote" } },
    //    { "phone1", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Buyer", "Company" } },
    //    { "phone2", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Buyer", "Company" } },
    //    { "fax", new List<string> { "DCompany", "Consignee", "InvoicingCompany", "Supplier", "Buyer", "Company", "Warehouse" } },
    //    { "contactperson", new List<string> { "Consignee", "Supplier", "Buyer", "Company", "Warehouse" } },
    //    { "iecodeno", new List<string> { "Consignee", "Company", "Supplier", "Buyer" } },
    //    { "bankname", new List<string> { "Consignee", "Company", "Supplier", "Buyer" } },
    //    { "bankaddress", new List<string> { "Consignee", "Company", "Supplier", "Buyer" } },
    //    { "bankswiftcode", new List<string> { "Consignee", "Company", "Supplier", "Buyer" } },
    //    { "internalstatus", new List<string> { "Buyer" } },
    //    { "rxlabel", new List<string> { "SaleOrderItemRetailTemp", "ShipRegisterForClient", "SaleOrderItemWholesaleTemp", "SaleOrderItemTemp", "Buyer", "IssueItem", "IssueItemTemp", "SalesOrderItem" } },
    //    { "addresslabel", new List<string> { "Buyer" } },
    //    { "deliverynote", new List<string> { "Buyer" } },
    //    { "dispensingfee1", new List<string> { "SaleOrderItemRetailTemp", "BuyerShippingTypeFee", "Buyer" } },
    //    { "dispensingfeen", new List<string> { "SalesOrder", "SaleOrderItemRetailTemp", "BuyerShippingTypeFee", "Buyer" } },
    //    { "shippingfee1", new List<string> { "SaleOrderItemRetailTemp", "BuyerShippingTypeFee", "Buyer" } },
    //    { "shippingfeen", new List<string> { "SalesOrder", "SaleOrderItemRetailTemp", "BuyerShippingTypeFee", "Buyer" } },
    //    { "creditdays", new List<string> { "Buyer" } },
    //    { "creditlimit", new List<string> { "Buyer" } },
    //    { "isimportiteminexistingorder", new List<string> { "Buyer" } },
    //    { "isdocumentrequired", new List<string> { "Buyer" } },
    //    { "billingdays", new List<string> { "Buyer" } },
    //    { "billingcycle", new List<string> { "Buyer" } },
    //    { "isautobilling", new List<string> { "Buyer" } },
    //    { "receiveinvoicebymail", new List<string> { "Buyer" } },
    //    { "invoiceemail", new List<string> { "Buyer" } },
    //    { "reviewpricechangealert", new List<string> { "Buyer" } },
    //    { "reviewstockinalert", new List<string> { "Buyer" } },
    //    { "returnshippingaddressid", new List<string> { "Buyer" } },
    //    { "printcn22", new List<string> { "Buyer" } },
    //    { "signaturetext", new List<string> { "Buyer" } },
    //    { "buyershippingtypefeeid", new List<string> { "BuyerShippingTypeFee" } },
    //    { "buyerwarehouseid", new List<string> { "BuyerWarehouse" } },
    //    { "preference", new List<string> { "BuyerWarehouse" } },
    //    { "cartontype", new List<string> { "CartonMaster" } },
    //    { "length", new List<string> { "CartonMaster" } },
    //    { "breadth", new List<string> { "CartonMaster" } },
    //    { "height", new List<string> { "CartonMaster" } },
    //    { "lxbxh", new List<string> { "CartonMaster" } },
    //    { "volumeincucm", new List<string> { "CartonMaster" } },
    //    { "lxbxhinmm", new List<string> { "CartonMaster" } },
    //    { "issuggestionrequired", new List<string> { "CartonMaster" } },
    //    { "categoryid", new List<string> { "CategoryId", "Category", "Products" } },
    //    { "chargeid", new List<string> { "POChargeTemp", "SaleInvoiceCharge", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "GoodsReceiptNoteCharge", "Charge", "ChargeId", "SaleInvoiceChargeTemp", "SaleOrderChargeTemp", "SaleOrderCharge", "POCharge", "GoodsReceiptNoteChargeTemp" } },
    //    { "symbol", new List<string> { "Charge", "Currency" } },
    //    { "chargetype", new List<string> { "Charge" } },
    //    { "chargecalculation", new List<string> { "Charge" } },
    //    { "chargeon", new List<string> { "Charge" } },
    //    { "cityid", new List<string> { "City" } },
    //    { "stateid", new List<string> { "StateId", "City", "State" } },
    //    { "cityname", new List<string> { "City" } },
    //    { "b2binvoiceid", new List<string> { "ClientInvoice", "ClientInvoiceItem" } },
    //    { "paymentduedate", new List<string> { "ClientInvoice" } },
    //    { "deeletedby", new List<string> { "ClientInvoice" } },
    //    { "created", new List<string> { "ClientInvoice", "Issue", "ClientInvoiceItem", "IssueItem" } },
    //    { "b2binvoiceitemid", new List<string> { "ClientInvoiceItem" } },
    //    { "issueitemid", new List<string> { "JMCInvoiceItem", "IssueItemId", "CreditNoteItem", "ClientInvoiceItem", "IssueItem", "IssueItemTemp", "SaleInvoiceItemTemp", "SaleInvoiceItem", "LongExpiryStockForIssue", "GoodsReceiptNoteItemTemp", "DummySaleInvoice", "ShortExpiryStockForIssue" } },
    //    { "companyid", new List<string> { "CompanyID", "SaleInvoice", "DebitNote", "JMCInvoice", "Warehouse", "GoodsReceiptNote", "PurchaseInvoice", "PurchaseOrder", "Company", "GoodsReturn" } },
    //    { "phone3", new List<string> { "DCompany", "Company", "InvoicingCompany" } },
    //    { "invoicingcompanyid", new List<string> { "Company", "InvoicingCompany" } },
    //    { "companydetails", new List<string> { "Company" } },
    //    { "countryid", new List<string> { "MapCountryTracking", "CountryVariation", "MapSGPCountryTracking", "DHLCountry", "Country", "State", "CountryId" } },
    //    { "countryvariationname", new List<string> { "CountryVariation" } },
    //    { "creditnoteid", new List<string> { "CreditNote", "CreditNoteID", "CreditNoteItem" } },
    //    { "saleinvoiceid", new List<string> { "CreditNote", "SaleInvoiceCharge", "SaleInvoiceId", "PaymentDetail", "SaleInvoice", "SaleInvoiceChargeTemp", "JMCInvoice", "InternalInvoiceChargeTemp", "SaleInvoiceItemTemp", "SaleInvoiceItem" } },
    //    { "creditnoteitemid", new List<string> { "CreditNoteItem" } },
    //    { "srno", new List<string> { "PendingIssues", "GoodsReceiptNoteItem", "PurchaseInvoiceCharge", "GoodsReceiptNoteCharge", "PurchaseOrderItemTemp", "PurchaseInvoiceItem", "SaleInvoiceItemTemp", "DebitNoteItem", "GoodsReceiptNoteItemTemp", "GoodsReturnItem", "CreditNoteItem", "GoodsReceiptNoteChargeTemp" } },
    //    { "productid", new List<string> { "ProductStoreLocation", "StockInAlert", "JMCInvoiceItem", "SaleOrderItemTemp", "DecideOrderStatus", "ProductPriceBackUp", "ProductId", "WinServicePendingIssue", "SaleInvoiceItem", "WarehouseProductStock", "SalesOrderItem", "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "ProductMonograph", "SaleInvoiceItemTemp", "DebitNoteItem", "LongExpiryStockForIssue", "PurchaseOrderItemTemp", "InventoryDetails", "Products", "DecideOrderStatus_GWS", "IssueItem", "ProductBin", "IssueItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "CreditNoteItem", "DummySaleInvoice", "ExcludeImportExportProduct", "ProductPrice", "ShortExpiryStockForIssue", "SaleOrderItemWholesaleTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "saleinvoiceitemid", new List<string> { "SaleInvoiceItem", "CreditNoteItem", "JMCInvoiceItem" } },
    //    { "addtostock", new List<string> { "CreditNoteItem" } },
    //    { "qty", new List<string> { "GoodsReceiptNoteItem", "PurchaseInvoiceItem", "DebitNoteItem", "PurchaseInvoiceItemTemp", "GoodsReceiptNoteItemTemp", "GoodsReturnItem", "CreditNoteItem" } },
    //    { "crate", new List<string> { "GoodsReceiptNoteItem", "SaleInvoiceItemTemp", "DebitNoteItem", "SaleInvoiceItem", "GoodsReceiptNoteItemTemp", "GoodsReturnItem", "CreditNoteItem" } },
    //    { "amount", new List<string> { "POChargeTemp", "SaleInvoiceCharge", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "JMCInvoiceItem", "SaleOrderCharge", "SaleInvoiceItem", "GoodsReceiptNoteItem", "PaymentDetail", "SaleInvoiceChargeTemp", "InternalInvoiceChargeTemp", "SaleInvoiceItemTemp", "DebitNoteItem", "POCharge", "GoodsReceiptNoteChargeTemp", "GoodsReceiptNoteCharge", "SaleOrderChargeTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "CreditNoteItem", "DummySaleInvoice", "GoodsReceiptNoteItemTemp", "GoodsReturnItem" } },
    //    { "camount", new List<string> { "SaleInvoiceCharge", "GoodsReceiptNoteItem", "SaleInvoiceItemTemp", "DebitNoteItem", "SaleInvoiceItem", "GoodsReturnItem", "CreditNoteItem" } },
    //    { "title", new List<string> { "MenuNew", "ShippingType", "OrderStatus", "Currency" } },
    //    { "namebeforedecimal", new List<string> { "Currency" } },
    //    { "nameafterdecimal", new List<string> { "Currency" } },
    //    { "currencyrateid", new List<string> { "CurrencyRate" } },
    //    { "date", new List<string> { "CurrencyRate" } },
    //    { "conversionrate", new List<string> { "CurrencyRate", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GoodsReceiptNote", "PurchaseInvoice", "PurchaseOrder" } },
    //    { "dcompanyid", new List<string> { "DCompany" } },
    //    { "debitnoteid", new List<string> { "DebitNote", "DebitNoteID", "DebitNoteItem" } },
    //    { "supplierid", new List<string> { "SupplierWarehouse", "InventoryDetails", "Supplier", "SupplierId", "DebitNote", "GoodsReceiptNote", "PurchaseInvoice", "UserSupplier", "PurchaseOrder", "SupplierBuyer", "GoodsReturn" } },
    //    { "purchaseinvoiceid", new List<string> { "PurchaseInvoiceId", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "DebitNote", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "PurchaseInvoice" } },
    //    { "supplierref", new List<string> { "DebitNote" } },
    //    { "debitnoteitemid", new List<string> { "DebitNoteItem" } },
    //    { "receiptitemid", new List<string> { "DebitNoteItem" } },
    //    { "purchaseinvoiceitemid", new List<string> { "PurchaseInvoiceItem", "DebitNoteItem" } },
    //    { "removefromstock", new List<string> { "DebitNoteItem" } },
    //    { "decideordershippingtypeid", new List<string> { "DecideOrderShippingType_GWS" } },
    //    { "shippingcode", new List<string> { "DecideOrderShippingType_GWS" } },
    //    { "decideorderstatusid", new List<string> { "DecideOrderStatus", "DecideOrderStatus_GWS" } },
    //    { "dhlcountrycode", new List<string> { "DHLCountry" } },
    //    { "itemidentifier", new List<string> { "ItemNumberStructure", "DHLItemNumberStructure", "SGPItemNumberStructure" } },
    //    { "itemnumberstart", new List<string> { "ItemNumberStructure", "DHLItemNumberStructure", "SGPItemNumberStructure" } },
    //    { "itemnumberend", new List<string> { "ItemNumberStructure", "DHLItemNumberStructure", "SGPItemNumberStructure" } },
    //    { "weightingfactor", new List<string> { "ItemNumberStructure", "DHLItemNumberStructure", "SGPItemNumberStructure" } },
    //    { "postcountrycode", new List<string> { "ItemNumberStructure", "DHLItemNumberStructure", "SGPItemNumberStructure" } },
    //    { "dosageid", new List<string> { "DosageId", "Dosage", "Products" } },
    //    { "dummysaleinvoiceid", new List<string> { "DummySaleInvoice" } },
    //    { "transactiontext", new List<string> { "IssueReport_ws", "SalesOrder", "PurchaseInvoice", "PurchaseOrder", "DummySaleInvoice", "GoodsReturn" } },
    //    { "transactionno", new List<string> { "SalesOrder", "PurchaseInvoice", "PurchaseOrder", "DummySaleInvoice", "GoodsReturn" } },
    //    { "transactiondate", new List<string> { "PurchaseInvoice", "SalesOrder", "DummySaleInvoice", "GoodsReturn" } },
    //    { "saleorderid", new List<string> { "SaleOrderItemRetailTemp", "JMCInvoiceItem", "SaleOrderItemWholesaleTemp", "Issue", "SaleOrderItemTemp", "SalesOrderId", "IssueReport_ws", "IssueItem", "SaleOrderChargeTemp", "SaleOrderCharge", "SaleInvoiceItemTemp", "SalesOrder", "SaleInvoiceItem", "DummySaleInvoice" } },
    //    { "quantity", new List<string> { "SaleOrderItemRetailTemp", "OrderServiceTemp", "JMCInvoiceItem", "SaleOrderItemWholesaleTemp", "SaleOrderItemTemp", "IssueItem", "IssueItemTemp", "SaleInvoiceItemTemp", "SaleInvoiceItem", "SalesOrderItem", "GSSImportTesting", "PurchaseOrderItem", "PurchaseOrderItemTemp", "DummySaleInvoice" } },
    //    { "count", new List<string> { "SaleOrderItemRetailTemp", "OrderServiceTemp", "JMCInvoiceItem", "Products", "SaleOrderItemTemp", "SaleOrderItemWholesaleTemp", "IssueItem", "IssueItemTemp", "SaleInvoiceItemTemp", "WinServicePendingIssue", "SaleInvoiceItem", "SalesOrderItem", "GSSImportTesting", "PurchaseOrderItem", "PurchaseOrderItemTemp", "DummySaleInvoice" } },
    //    { "units", new List<string> { "SaleOrderItemRetailTemp", "OrderServiceTemp", "JMCInvoiceItem", "Products", "SaleOrderItemTemp", "SaleOrderItemWholesaleTemp", "IssueItem", "IssueItemTemp", "SaleInvoiceItemTemp", "WinServicePendingIssue", "SaleInvoiceItem", "SalesOrderItem", "GSSImportTesting", "PurchaseOrderItem", "PurchaseOrderItemTemp", "DummySaleInvoice" } },
    //    { "errorid", new List<string> { "ErrorLog" } },
    //    { "exceptionmessage", new List<string> { "ErrorLog" } },
    //    { "innerexceptionmessage", new List<string> { "ErrorLog" } },
    //    { "sender", new List<string> { "ErrorLog" } },
    //    { "event", new List<string> { "ErrorLog" } },
    //    { "errordate", new List<string> { "ErrorLog" } },
    //    { "goodsreceiptnoteid", new List<string> { "GoodsReceiptNoteItem", "GoodsReceiptNoteCharge", "IssueItemTemp", "GoodsReceiptNote", "GoodsReceiptNoteId", "SheetLocation", "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteChargeTemp" } },
    //    { "transactiontypeid", new List<string> { "TransactionType", "Margin", "TransactionTypeId", "SaleInvoice", "GoodsReceiptNote", "PurchaseInvoice", "PurchaseOrder", "GoodsReturn" } },
    //    { "dcno", new List<string> { "GoodsReceiptNote" } },
    //    { "dcdate", new List<string> { "GoodsReceiptNote" } },
    //    { "taxtotalamount", new List<string> { "PurchaseInvoice", "PurchaseOrder", "GoodsReceiptNote", "SaleInvoice" } },
    //    { "grandtotalamount", new List<string> { "PurchaseOrder", "GoodsReceiptNote" } },
    //    { "cgrandtotalamount", new List<string> { "PurchaseOrder", "GoodsReceiptNote" } },
    //    { "customsbillofentryno", new List<string> { "GoodsReceiptNote" } },
    //    { "grnno", new List<string> { "GoodsReceiptNote" } },
    //    { "stockowner", new List<string> { "GoodsReceiptNote" } },
    //    { "updatecostmrptomaster", new List<string> { "PurchaseInvoice", "GoodsReceiptNote" } },
    //    { "transactionstatusid", new List<string> { "Issue", "IssueReport_ws", "SaleInvoice", "SalesOrder", "WinServicePendingIssue", "GoodsReceiptNote", "PurchaseInvoice", "PurchaseOrder", "TransactionStatus" } },
    //    { "customsbillofentrydate", new List<string> { "GoodsReceiptNote" } },
    //    { "goodsreceiptnotechargeid", new List<string> { "GoodsReceiptNoteCharge" } },
    //    { "percentage", new List<string> { "POChargeTemp", "SaleInvoiceCharge", "PurchaseInvoiceCharge", "PurchaseInvoiceChargeTemp", "GoodsReceiptNoteCharge", "SaleInvoiceChargeTemp", "SaleOrderChargeTemp", "SaleOrderCharge", "POCharge", "GoodsReceiptNoteChargeTemp" } },
    //    { "goodsreturnid", new List<string> { "PurchaseInvoiceCharge", "GoodsReceiptNoteCharge", "GoodsReceiptNoteChargeTemp", "GoodsReturnId", "GoodsReturnItem", "GoodsReturn" } },
    //    { "goodsreceiptnotechargetempid", new List<string> { "GoodsReceiptNoteChargeTemp" } },
    //    { "sessionid", new List<string> { "POChargeTemp", "SaleOrderItemRetailTemp", "PurchaseInvoiceChargeTemp", "SaleOrderItemWholesaleTemp", "SaleOrderItemTemp", "SaleInvoiceChargeTemp", "IssueReport_ws", "POTermsTemp", "PurchaseOrderItemTemp", "SaleOrderChargeTemp", "IssueItemTemp", "SaleInvoiceItemTemp", "PurchaseInvoiceItemTemp", "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteChargeTemp" } },
    //    { "goodsreceiptnoteitemid", new List<string> { "GoodsReceiptNoteItem", "IssueItem", "IssueItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GoodsReceiptNoteItemId", "LongExpiryStockForIssue", "GoodsReceiptNoteItemTemp", "GoodsReturnItem", "ShortExpiryStockForIssue" } },
    //    { "purchaseorderitemid", new List<string> { "PurchaseOrderItemId", "GoodsReceiptNoteItem", "PurchaseOrderItemTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp" } },
    //    { "dcqty", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "rejectedqty", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "rejectionnote", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "mfgdate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "expirydate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "remark", new List<string> { "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "JMCInvoiceItem", "SaleOrderItemWholesaleTemp", "Issue", "SaleOrderItemTemp", "IssueItem", "PurchaseOrderItemTemp", "IssueItemTemp", "PurchaseInvoiceItem", "Patient", "PurchaseInvoiceItemTemp", "SaleInvoiceItem", "SaleInvoiceItemTemp", "PurchaseOrderItem", "WinServicePendingIssue", "GoodsReceiptNoteItemTemp", "SalesOrderItem" } },
    //    { "note", new List<string> { "SaleOrderItemRetailTemp", "GoodsReceiptNoteItem", "JMCInvoiceItem", "SaleOrderItemWholesaleTemp", "SaleOrderItemTemp", "ShipRegisterForClient", "IssueItem", "PurchaseOrderItemTemp", "IssueItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "Payment", "SaleInvoiceItem", "SaleInvoiceItemTemp", "PurchaseOrderItem", "GoodsReceiptNoteItemTemp", "SalesOrderItem" } },
    //    { "stockqty", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "invoicebalqty", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "debitnotebalqty", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "previousrate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "cpreviousrate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "mrp", new List<string> { "ProductPrice", "GoodsReceiptNoteItem", "ProductPriceBackUp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "GoodsReceiptNoteItemTemp" } },
    //    { "receiptdate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "goodsreturnbalqty", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "pricelistrate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "dispensedmanufacturer", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "location", new List<string> { "SheetLocation", "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "boeno", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "boedate", new List<string> { "GoodsReceiptNoteItemTemp", "GoodsReceiptNoteItem" } },
    //    { "usdgrandtotal", new List<string> { "GoodsReceiptNoteItemTemp" } },
    //    { "purchaseinvoicebalamount", new List<string> { "GoodsReturn" } },
    //    { "goodsreturnitemid", new List<string> { "GoodsReturnItem" } },
    //    { "groupid", new List<string> { "Group", "GroupId", "Products" } },
    //    { "buyerorderno", new List<string> { "GSSImportTesting", "SalesOrder", "IssueReport_ws" } },
    //    { "buyerorderdate", new List<string> { "GSSImportTesting", "SalesOrder" } },
    //    { "firstname", new List<string> { "GSSImportTesting", "Patient" } },
    //    { "lastname", new List<string> { "GSSImportTesting", "Patient" } },
    //    { "directions", new List<string> { "GSSImportTesting" } },
    //    { "patientname", new List<string> { "GSSImportTesting", "SaleOrderItemTemp", "SaleOrderItemRetailTemp", "SalesOrderItem" } },
    //    { "doctorname", new List<string> { "SaleOrderItemRetailTemp", "OrderServiceTemp", "SaleOrderItemTemp", "Patient", "GSSImportTesting", "SalesOrderItem" } },
    //    { "refillbalance", new List<string> { "SaleOrderItemRetailTemp", "SaleOrderItemTemp", "Patient", "GSSImportTesting", "SalesOrderItem" } },
    //    { "rxreference", new List<string> { "GSSImportTesting", "SaleOrderItemRetailTemp", "Patient", "SalesOrderItem" } },
    //    { "rxamount", new List<string> { "SaleOrderItemRetailTemp", "SaleOrderItemTemp", "Patient", "GSSImportTesting", "SalesOrderItem" } },
    //    { "orderpdfpath", new List<string> { "GSSImportTesting", "SalesOrder", "OrderServiceTemp" } },
    //    { "shippingtype", new List<string> { "GSSImportTesting", "IssueReport_ws" } },
    //    { "patientcontactno", new List<string> { "GSSImportTesting", "SaleOrderItemRetailTemp", "Patient", "OrderServiceTemp" } },
    //    { "doctorcontactno", new List<string> { "GSSImportTesting", "SaleOrderItemRetailTemp", "Patient" } },
    //    { "pharmacycomment", new List<string> { "GSSImportTesting", "SalesOrder", "ShipRegisterForClient" } },
    //    { "identityid", new List<string> { "IdentityId", "Products", "Identity" } },
    //    { "ineternalinvoicechargeid", new List<string> { "InternalInvoiceChargeTemp" } },
    //    { "websessionid", new List<string> { "InternalInvoiceChargeTemp" } },
    //    { "grandtotal", new List<string> { "PurchaseInvoice", "JMCInvoice", "InternalInvoiceChargeTemp", "SaleInvoice" } },
    //    { "lastsupplier", new List<string> { "InventoryDetails" } },
    //    { "lastorderdate", new List<string> { "InventoryDetails" } },
    //    { "lastpoprice", new List<string> { "InventoryDetails" } },
    //    { "currency", new List<string> { "InventoryDetails" } },
    //    { "lastpopriceinusd", new List<string> { "InventoryDetails" } },
    //    { "reorderpoint", new List<string> { "InventoryDetails" } },
    //    { "usablestock", new List<string> { "InventoryDetails" } },
    //    { "reorderqty", new List<string> { "InventoryDetails" } },
    //    { "criticalstockpoint", new List<string> { "InventoryDetails" } },
    //    { "onorderqty", new List<string> { "InventoryDetails" } },
    //    { "stockinhand", new List<string> { "InventoryDetails" } },
    //    { "transitstock", new List<string> { "WarehouseProductStock", "InventoryDetails" } },
    //    { "discardqty", new List<string> { "InventoryDetails" } },
    //    { "issueno", new List<string> { "Issue" } },
    //    { "autobatchid", new List<string> { "Issue" } },
    //    { "autobatchdate", new List<string> { "Issue" } },
    //    { "buyeraffiliateid", new List<string> { "Issue", "SalesOrder" } },
    //    { "noofboxes", new List<string> { "Issue", "IssueReport_ws" } },
    //    { "boxsize", new List<string> { "Issue", "Products", "IssueReport_ws" } },
    //    { "registerno", new List<string> { "ShipRegisterForClient", "Issue", "IssueReport_ws" } },
    //    { "shipdate", new List<string> { "ShipRegisterForClient", "Issue", "IssueReport_ws" } },
    //    { "shipcost", new List<string> { "Issue", "IssueReport_ws" } },
    //    { "issuetypeid", new List<string> { "Issue", "IssueReport_ws" } },
    //    { "totalweight", new List<string> { "IssueItem", "Issue", "IssueItemTemp", "IssueReport_ws" } },
    //    { "grossweight", new List<string> { "Issue", "IssueBoxweight" } },
    //    { "modified", new List<string> { "IssueItem", "Issue" } },
    //    { "modifiedby", new List<string> { "IssueItem", "Issue", "ProductMonograph" } },
    //    { "uploaded", new List<string> { "IssueItem", "Issue" } },
    //    { "cancelledby", new List<string> { "Issue" } },
    //    { "cancelleddate", new List<string> { "Issue" } },
    //    { "ispicklistprinted", new List<string> { "Issue" } },
    //    { "isunifiedprinted", new List<string> { "Issue" } },
    //    { "isrxlabelprinted", new List<string> { "Issue" } },
    //    { "isprealertprinted", new List<string> { "Issue" } },
    //    { "isrxlabelmprinted", new List<string> { "Issue" } },
    //    { "ispdocprinted", new List<string> { "Issue" } },
    //    { "isaddressprinted", new List<string> { "Issue" } },
    //    { "istrackingupdated", new List<string> { "Issue" } },
    //    { "contenttype", new List<string> { "Issue", "Products" } },
    //    { "bagno", new List<string> { "Issue" } },
    //    { "b2bboxno", new List<string> { "Issue", "TrnBoxDetails" } },
    //    { "isb2binvoicecreated", new List<string> { "Issue" } },
    //    { "b2bboxtype", new List<string> { "Issue", "TrnBoxDetails" } },
    //    { "batchreportid", new List<string> { "IssueBatchReport" } },
    //    { "dateprocessed", new List<string> { "IssueBatchReport" } },
    //    { "comment", new List<string> { "IssueBatchReport" } },
    //    { "preparedby", new List<string> { "IssueBatchReport" } },
    //    { "issueboxweightid", new List<string> { "IssueBoxweight" } },
    //    { "boxno", new List<string> { "IssueItem", "IssueItemTemp", "IssueBoxweight" } },
    //    { "issuedate", new List<string> { "IssueItem" } },
    //    { "saleorderitemid", new List<string> { "IssueItem", "SaleOrderItemRetailTemp", "SalesOrderItemId", "SalesOrderItem" } },
    //    { "weight", new List<string> { "IssueItem", "IssueItemTemp" } },
    //    { "saleinvoicebalqty", new List<string> { "IssueItem" } },
    //    { "issuereceiptbalqty", new List<string> { "IssueItem" } },
    //    { "creditnotebalqty", new List<string> { "IssueItem" } },
    //    { "isshipped", new List<string> { "IssueItem" } },
    //    { "productidentity", new List<string> { "IssueItemTemp" } },
    //    { "saleorderno", new List<string> { "IssueItemTemp" } },
    //    { "shipped", new List<string> { "IssueItemTemp" } },
    //    { "receiptno", new List<string> { "IssueItemTemp" } },
    //    { "receipttransdate", new List<string> { "IssueItemTemp" } },
    //    { "salesorderitemid", new List<string> { "SalesOrderItemId", "IssueItemTemp", "WinServicePendingIssue", "SaleInvoiceItemTemp", "SalesOrderItem" } },
    //    { "warehousename", new List<string> { "IssueReport_ws" } },
    //    { "status", new List<string> { "PendingIssues", "TransactionStatus", "OrderServiceTemp", "IssueReport_ws" } },
    //    { "batchdate", new List<string> { "IssueReport_ws" } },
    //    { "issuetextid", new List<string> { "IssueText" } },
    //    { "issuetext", new List<string> { "IssueText" } },
    //    { "batchnumbertext", new List<string> { "IssueText" } },
    //    { "noofordersperbatch", new List<string> { "IssueText" } },
    //    { "delivernotenostart", new List<string> { "IssueText" } },
    //    { "batchnostart", new List<string> { "IssueText" } },
    //    { "jmcclientid", new List<string> { "JMCClient" } },
    //    { "jmcmasterid", new List<string> { "JMCClient", "JMCMaster" } },
    //    { "jmcclientcode", new List<string> { "JMCClient" } },
    //    { "jmcclientname", new List<string> { "JMCClient" } },
    //    { "jmcclientaddress", new List<string> { "JMCClient" } },
    //    { "jmcclientdispensingfees", new List<string> { "JMCClient" } },
    //    { "jmcclientshippingfees", new List<string> { "JMCClient" } },
    //    { "jmcclientpricetypeid", new List<string> { "JMCClient" } },
    //    { "jmcclientusername", new List<string> { "JMCClient" } },
    //    { "jmcclientpassword", new List<string> { "JMCClient" } },
    //    { "isdeleted", new List<string> { "JMCClient", "JMCInvoice", "JMCMaster", "JMCInvoiceItem" } },
    //    { "jmcinvoiceid", new List<string> { "JMCInvoiceId", "JMCInvoice", "JMCInvoiceItem" } },
    //    { "jmcinvoiceno", new List<string> { "JMCInvoice" } },
    //    { "jmcinvoiceitemid", new List<string> { "JMCInvoiceItem" } },
    //    { "dispensingfee", new List<string> { "SalesOrder", "SaleInvoiceItemTemp", "SaleInvoiceItem", "JMCInvoiceItem" } },
    //    { "shippingfee", new List<string> { "SalesOrder", "SaleInvoiceItemTemp", "SaleInvoiceItem", "JMCInvoiceItem" } },
    //    { "jmccode", new List<string> { "JMCMaster" } },
    //    { "jmcname", new List<string> { "JMCMaster" } },
    //    { "jmcaddress", new List<string> { "JMCMaster" } },
    //    { "jmcinvoiceseries", new List<string> { "JMCMaster" } },
    //    { "jmcusername", new List<string> { "JMCMaster" } },
    //    { "jmcpassword", new List<string> { "JMCMaster" } },
    //    { "scheduledate", new List<string> { "JobScheduleCriteria" } },
    //    { "fromdate", new List<string> { "JobScheduleCriteria" } },
    //    { "todate", new List<string> { "JobScheduleCriteria" } },
    //    { "reportname", new List<string> { "JobScheduleCriteria" } },
    //    { "longexpiryforissueid", new List<string> { "LongExpiryStockForIssue" } },
    //    { "isissued", new List<string> { "LongExpiryStockForIssue", "ShortExpiryStockForIssue" } },
    //    { "addedondate", new List<string> { "LongExpiryStockForIssue", "ShortExpiryStockForIssue" } },
    //    { "addedby", new List<string> { "LongExpiryStockForIssue", "ShortExpiryStockForIssue" } },
    //    { "deletedondate", new List<string> { "LongExpiryStockForIssue", "ShortExpiryStockForIssue" } },
    //    { "manufacturerid", new List<string> { "ManufacturerId", "Manufacturer", "Products" } },
    //    { "marginid", new List<string> { "Margin" } },
    //    { "margintype", new List<string> { "Margin" } },
    //    { "marginpercentage", new List<string> { "Margin" } },
    //    { "marketedbyid", new List<string> { "MarketedBy", "Products" } },
    //    { "menuid", new List<string> { "MenuNew", "Menu", "MenuId" } },
    //    { "menutitle", new List<string> { "Menu" } },
    //    { "menulink", new List<string> { "Menu" } },
    //    { "parentmenuid", new List<string> { "MenuNew", "Menu", "MenuId" } },
    //    { "menugroupid", new List<string> { "MenuNew" } },
    //    { "type", new List<string> { "MenuNew" } },
    //    { "url", new List<string> { "MenuNew" } },
    //    { "icon", new List<string> { "MenuNew" } },
    //    { "breadcrumbs", new List<string> { "MenuNew" } },
    //    { "sortorder", new List<string> { "MenuNew" } },
    //    { "modulename", new List<string> { "Module" } },
    //    { "boxtype", new List<string> { "MstB2BBoxTypes" } },
    //    { "orderserviceid", new List<string> { "OrderServiceTemp" } },
    //    { "supplierproductcode", new List<string> { "OrderServiceTemp" } },
    //    { "supplierproductmultiplier", new List<string> { "OrderServiceTemp" } },
    //    { "direction", new List<string> { "OrderServiceTemp" } },
    //    { "isrefill", new List<string> { "OrderServiceTemp" } },
    //    { "clientname", new List<string> { "OrderServiceTemp" } },
    //    { "clientcode", new List<string> { "OrderServiceTemp" } },
    //    { "patientfirstname", new List<string> { "OrderServiceTemp" } },
    //    { "patientlastname", new List<string> { "OrderServiceTemp" } },
    //    { "patientdob", new List<string> { "OrderServiceTemp" } },
    //    { "patientallergies", new List<string> { "OrderServiceTemp" } },
    //    { "saddressline1", new List<string> { "OrderServiceTemp" } },
    //    { "saddressline2", new List<string> { "OrderServiceTemp" } },
    //    { "scity", new List<string> { "OrderServiceTemp" } },
    //    { "sstate", new List<string> { "OrderServiceTemp" } },
    //    { "scountry", new List<string> { "OrderServiceTemp" } },
    //    { "szip", new List<string> { "OrderServiceTemp" } },
    //    { "residentialaddress", new List<string> { "OrderServiceTemp" } },
    //    { "movedtoprinted", new List<string> { "OrderServiceTemp" } },
    //    { "gomsbuyercode", new List<string> { "OrderServiceTemp" } },
    //    { "isaddedtoordertable", new List<string> { "OrderServiceTemp" } },
    //    { "chargetocustomer", new List<string> { "OrderServiceTemp" } },
    //    { "client", new List<string> { "OrderServiceTemp" } },
    //    { "buyer", new List<string> { "OrderServiceTemp" } },
    //    { "orderstatusid", new List<string> { "OrderStatusId", "SalesOrder", "OrderStatus" } },
    //    { "patientid", new List<string> { "Patient", "SalesOrderItem" } },
    //    { "patientdocumentpathid", new List<string> { "PatientDocument" } },
    //    { "documentpath", new List<string> { "PatientDocument" } },
    //    { "paymentid", new List<string> { "PaymentDetail", "Payment", "PaymentId" } },
    //    { "dateofreceipt", new List<string> { "Payment" } },
    //    { "paymenttypeid", new List<string> { "PaymentType", "Payment", "PaymentTypeId" } },
    //    { "netbalanceamount", new List<string> { "Payment" } },
    //    { "paymentdetailid", new List<string> { "PaymentDetail" } },
    //    { "invoicebalamount", new List<string> { "PaymentDetail" } },
    //    { "enteredat", new List<string> { "PendingIssues" } },
    //    { "pobillingdetailsid", new List<string> { "POBillingDetailsID", "POBillingDetails", "PurchaseOrder" } },
    //    { "billtocontactperson", new List<string> { "POBillingDetails" } },
    //    { "billaddress", new List<string> { "POBillingDetails" } },
    //    { "billcity", new List<string> { "POBillingDetails" } },
    //    { "billstate", new List<string> { "POBillingDetails" } },
    //    { "billzip", new List<string> { "POBillingDetails" } },
    //    { "billcountry", new List<string> { "POBillingDetails" } },
    //    { "purchaseorderid", new List<string> { "POChargeTemp", "PurchaseOrderId", "POTermsTemp", "PurchaseOrderItemTemp", "POCharge", "PurchaseOrderItem", "PurchaseOrder", "POTerms" } },
    //    { "chargeamount", new List<string> { "POChargeTemp", "PurchaseInvoiceChargeTemp", "SaleInvoiceChargeTemp", "SaleOrderChargeTemp", "SaleOrderCharge", "POCharge" } },
    //    { "poshippingdetailsid", new List<string> { "POShippingDetails", "PurchaseOrder", "POShippingDetailsId" } },
    //    { "shiptocontactperson", new List<string> { "POShippingDetails" } },
    //    { "shipaddress", new List<string> { "POShippingDetails" } },
    //    { "shipcity", new List<string> { "POShippingDetails" } },
    //    { "shipstate", new List<string> { "POShippingDetails" } },
    //    { "shipzip", new List<string> { "POShippingDetails" } },
    //    { "shipcountry", new List<string> { "POShippingDetails" } },
    //    { "potermid", new List<string> { "POTerms" } },
    //    { "termid", new List<string> { "TermId", "POTermsTemp", "Terms", "POTerms" } },
    //    { "pricecodeid", new List<string> { "PriceCodeID", "Products", "PriceCode" } },
    //    { "productbinid", new List<string> { "ProductBin" } },
    //    { "monographid", new List<string> { "ProductMonograph" } },
    //    { "monograph1", new List<string> { "ProductMonograph" } },
    //    { "monograph2", new List<string> { "ProductMonograph" } },
    //    { "monograph3", new List<string> { "ProductMonograph" } },
    //    { "monograph4", new List<string> { "ProductMonograph" } },
    //    { "monographdesc", new List<string> { "ProductMonograph" } },
    //    { "uploadedby", new List<string> { "ProductMonograph" } },
    //    { "productpriceid", new List<string> { "ProductPrice" } },
    //    { "productcost", new List<string> { "ProductPrice", "ProductPriceBackUp" } },
    //    { "othercharges", new List<string> { "ProductPrice", "ProductPriceBackUp" } },
    //    { "landedcost", new List<string> { "ProductPrice", "ProductPriceBackUp" } },
    //    { "landedcostcurrencyid", new List<string> { "ProductPrice", "ProductPriceBackUp" } },
    //    { "updatedate", new List<string> { "ProductPrice", "ProductPriceBackUp" } },
    //    { "lastupdatedate", new List<string> { "ProductPrice", "ProductPriceBackUp" } },
    //    { "priceupdatecomment", new List<string> { "ProductPrice", "ProductPriceBackUp", "Products" } },
    //    { "productpricebkid", new List<string> { "ProductPriceBackUp" } },
    //    { "inventorycode", new List<string> { "Products" } },
    //    { "alternatecode", new List<string> { "Products" } },
    //    { "indianbrandname", new List<string> { "Products" } },
    //    { "mfgapproval", new List<string> { "Products" } },
    //    { "strength", new List<string> { "Products" } },
    //    { "unitid", new List<string> { "UnitId", "Unit", "Products" } },
    //    { "packsize", new List<string> { "Products" } },
    //    { "multiplier", new List<string> { "Products" } },
    //    { "packweight", new List<string> { "Products" } },
    //    { "boxweight", new List<string> { "Products" } },
    //    { "presentation", new List<string> { "Products" } },
    //    { "countryname", new List<string> { "SGPCountry", "Products" } },
    //    { "labelling", new List<string> { "Products" } },
    //    { "productlisted", new List<string> { "Products" } },
    //    { "purchaserscomment", new List<string> { "Products" } },
    //    { "pharmacycode", new List<string> { "Products" } },
    //    { "pharmacymultiplier", new List<string> { "Products" } },
    //    { "reorderquantity", new List<string> { "Products" } },
    //    { "humanvat", new List<string> { "Products" } },
    //    { "sourcecategory", new List<string> { "Products" } },
    //    { "productnature", new List<string> { "Products" } },
    //    { "istopproduct", new List<string> { "Products" } },
    //    { "isblocked", new List<string> { "Products" } },
    //    { "japanesedescription", new List<string> { "Products" } },
    //    { "productpriority", new List<string> { "Products" } },
    //    { "lengthmm", new List<string> { "Products" } },
    //    { "heightmm", new List<string> { "Products" } },
    //    { "widthmm", new List<string> { "Products" } },
    //    { "tarevolume", new List<string> { "Products" } },
    //    { "producttype", new List<string> { "Products" } },
    //    { "storelocation", new List<string> { "ProductStoreLocation" } },
    //    { "supplierinvoiceno", new List<string> { "PurchaseInvoice" } },
    //    { "supplierinvoicedate", new List<string> { "PurchaseInvoice" } },
    //    { "cgrandtotal", new List<string> { "PurchaseInvoice", "SaleInvoice" } },
    //    { "purchaseinvoicechargeid", new List<string> { "PurchaseInvoiceCharge" } },
    //    { "othercharge", new List<string> { "SaleInvoiceItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "SaleInvoiceItem" } },
    //    { "cothercharge", new List<string> { "SaleInvoiceItemTemp", "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp", "SaleInvoiceItem" } },
    //    { "effrate", new List<string> { "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp" } },
    //    { "ceffrate", new List<string> { "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp" } },
    //    { "previousmrp", new List<string> { "PurchaseInvoiceItem", "PurchaseInvoiceItemTemp" } },
    //    { "usdtotalamount", new List<string> { "PurchaseInvoiceItemTemp" } },
    //    { "purchaseorderdate", new List<string> { "PurchaseOrder" } },
    //    { "quotationno", new List<string> { "PurchaseOrder" } },
    //    { "quotationdate", new List<string> { "PurchaseOrder" } },
    //    { "purchaseorderstatus", new List<string> { "PurchaseOrder" } },
    //    { "receivedquantity", new List<string> { "PurchaseOrderItem", "PurchaseOrderItemTemp" } },
    //    { "deliveryremark", new List<string> { "PurchaseOrderItem", "PurchaseOrderItemTemp" } },
    //    { "deliverydate", new List<string> { "PurchaseOrderItem", "PurchaseOrderItemTemp", "ShipRegisterForClient" } },
    //    { "deliverystatus", new List<string> { "PurchaseOrderItem" } },
    //    { "deliveryqty", new List<string> { "PurchaseOrderItem" } },
    //    { "boxnumbersid", new List<string> { "REGBoxNumberDetail", "REGBoxNumberStructure" } },
    //    { "boxnumber", new List<string> { "REGBoxNumberDetail" } },
    //    { "createdon", new List<string> { "REGBoxNumberDetail" } },
    //    { "prefix", new List<string> { "REGBoxNumberStructure" } },
    //    { "numberstartprefix", new List<string> { "REGBoxNumberStructure" } },
    //    { "numberstart", new List<string> { "REGBoxNumberStructure" } },
    //    { "sufix", new List<string> { "REGBoxNumberStructure" } },
    //    { "post", new List<string> { "REGBoxNumberStructure" } },
    //    { "paawb", new List<string> { "REGIssueShipmentDetail" } },
    //    { "addressid", new List<string> { "ReturnShippingAddress" } },
    //    { "balanceamount", new List<string> { "SaleInvoice" } },
    //    { "duedays", new List<string> { "SaleInvoice" } },
    //    { "duedate", new List<string> { "SaleInvoice" } },
    //    { "airline", new List<string> { "SaleInvoice" } },
    //    { "awbpdfpath", new List<string> { "SaleInvoice" } },
    //    { "shippingbillno", new List<string> { "SaleInvoice" } },
    //    { "shippingbilldate", new List<string> { "SaleInvoice" } },
    //    { "saleinvoicechargeid", new List<string> { "SaleInvoiceCharge" } },
    //    { "intinvoiceplrate", new List<string> { "SaleInvoiceItem" } },
    //    { "jmcrate", new List<string> { "SaleInvoiceItem", "SalesOrderItem" } },
    //    { "saleinvoiceitemtempid", new List<string> { "SaleInvoiceItemTemp" } },
    //    { "saleorderitemretailtempid", new List<string> { "SaleOrderItemRetailTemp" } },
    //    { "productrelatedcomment", new List<string> { "SaleOrderItemWholesaleTemp", "SaleOrderItemRetailTemp", "SalesOrderItem" } },
    //    { "verified", new List<string> { "SaleOrderItemWholesaleTemp", "SaleOrderItemRetailTemp", "SalesOrderItem" } },
    //    { "manufacturer", new List<string> { "SaleOrderItemWholesaleTemp", "SaleOrderItemRetailTemp" } },
    //    { "saleorderitemtempid", new List<string> { "SaleOrderItemWholesaleTemp", "SaleOrderItemTemp" } },
    //    { "issuequantity", new List<string> { "SaleOrderItemTemp", "SalesOrderItem" } },
    //    { "rxref", new List<string> { "SaleOrderItemTemp" } },
    //    { "orderamount", new List<string> { "SalesOrder" } },
    //    { "ordertaxamount", new List<string> { "SalesOrder" } },
    //    { "orderpatientid", new List<string> { "SalesOrder" } },
    //    { "ordertype", new List<string> { "TransactionType", "SalesOrder", "TransactionTypeId" } },
    //    { "ordergrossamount", new List<string> { "SalesOrder" } },
    //    { "ispartial", new List<string> { "SalesOrder" } },
    //    { "isauthorised", new List<string> { "SalesOrder" } },
    //    { "authorisedby", new List<string> { "SalesOrder" } },
    //    { "authorisedcomment", new List<string> { "SalesOrder" } },
    //    { "ordernote", new List<string> { "SalesOrder" } },
    //    { "isnormalorder", new List<string> { "SalesOrder" } },
    //    { "isproductcostzero", new List<string> { "SalesOrder" } },
    //    { "isallcostzero", new List<string> { "SalesOrder" } },
    //    { "reasonforshipment", new List<string> { "SalesOrder" } },
    //    { "orderstatusreasonid", new List<string> { "SalesOrder" } },
    //    { "updatedon", new List<string> { "SalesOrder", "UserPasswordHistory" } },
    //    { "shippingfees", new List<string> { "SalesOrderItem" } },
    //    { "dispensingfees", new List<string> { "SalesOrderItem" } },
    //    { "shiporderquantity", new List<string> { "SalesOrderItem" } },
    //    { "invoicequantity", new List<string> { "SalesOrderItem" } },
    //    { "backorderquantity", new List<string> { "SalesOrderItem" } },
    //    { "changeid", new List<string> { "SchemaChangeLog" } },
    //    { "changetime", new List<string> { "SchemaChangeLog" } },
    //    { "eventddl", new List<string> { "SchemaChangeLog" } },
    //    { "sgpreqrespid", new List<string> { "SGPApiLog" } },
    //    { "servicetype", new List<string> { "SGPApiLog" } },
    //    { "methodname", new List<string> { "SGPApiLog" } },
    //    { "soapxml", new List<string> { "SGPApiLog" } },
    //    { "issucess", new List<string> { "SGPApiLog" } },
    //    { "sgpcountryid", new List<string> { "SGPCountry" } },
    //    { "countrycode", new List<string> { "SGPCountry" } },
    //    { "shipmentnumber", new List<string> { "SGPIssueShipmentDetail" } },
    //    { "shipmentlabelpath", new List<string> { "SGPIssueShipmentDetail" } },
    //    { "isassigned", new List<string> { "SGPIssueShipmentDetail" } },
    //    { "assigneddate", new List<string> { "SGPIssueShipmentDetail" } },
    //    { "requestlogid", new List<string> { "SGPWebRequest" } },
    //    { "xmlrequest", new List<string> { "SGPWebRequest" } },
    //    { "requestname", new List<string> { "SGPWebRequest" } },
    //    { "deliveryno", new List<string> { "ShipRegisterForClient" } },
    //    { "deliverynotestatus", new List<string> { "ShipRegisterForClient" } },
    //    { "productcomment", new List<string> { "ShipRegisterForClient" } },
    //    { "transstatus", new List<string> { "ShipRegisterForClient" } },
    //    { "shortexpiryforissueid", new List<string> { "ShortExpiryStockForIssue" } },
    //    { "statename", new List<string> { "State" } },
    //    { "stockinalertid", new List<string> { "StockInAlert" } },
    //    { "stockindate", new List<string> { "StockInAlert" } },
    //    { "b2bgrossweight", new List<string> { "TrnBoxDetails" } },
    //    { "trackingno", new List<string> { "TrnBoxDetails" } },
    //    { "parcelweight", new List<string> { "TrnBoxDetails" } },
    //    { "parceltype", new List<string> { "TrnBoxDetails" } },
    //    { "b2bboxweight", new List<string> { "TrnBoxDetails" } },
    //    { "createddate", new List<string> { "TrnBoxDetails" } },
    //    { "userpassword", new List<string> { "User" } },
    //    { "roleid", new List<string> { "User" } },
    //    { "emailid", new List<string> { "User" } },
    //    { "usertypeid", new List<string> { "User" } },
    //    { "oldpassword", new List<string> { "UserPasswordHistory" } },
    //    { "nameforclient", new List<string> { "Warehouse" } },
    //    { "origincity", new List<string> { "Warehouse" } },
    //    { "licensenumber", new List<string> { "Warehouse" } },
    //    { "contactdirectline", new List<string> { "Warehouse" } },
    //    { "contactboardline", new List<string> { "Warehouse" } },
    //    { "contactmobile", new List<string> { "Warehouse" } },
    //    { "expirylimit", new List<string> { "Warehouse" } },
    //    { "maxordersperday", new List<string> { "Warehouse" } },
    //    { "warehouseproductstockid", new List<string> { "WarehouseProductStock" } },
    //    { "stock", new List<string> { "WarehouseProductStock" } },
    //    { "autoissueid", new List<string> { "WinServicePendingIssue" } },
    //    { "autoissuedate", new List<string> { "WinServicePendingIssue" } },
    //    { "orderquantity", new List<string> { "WinServicePendingIssue" } },
    //    { "warehousestockquantity", new List<string> { "WinServicePendingIssue" } },
    //    { "businesstype", new List<string> { "WinServicePendingIssue" } },
    //};
    //    }

    }
}
