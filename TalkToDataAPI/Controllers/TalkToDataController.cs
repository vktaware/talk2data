using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using Microsoft.Extensions.Configuration;
using TalkToDataAPI.Models;
using System.Text.Json;
using System.Net.Http;
using System.Threading.Tasks;
using TalkToDataAPI.Services;


namespace TalkToDataAPI.Controllers
{
    [Route("api/[controller]")]
    [ApiController]
    public class TalkToDataController : ControllerBase
    {
        private readonly IConfiguration _configuration;
        private readonly HttpClient _httpClient;

        public TalkToDataController(IConfiguration configuration)
        {
            _configuration = configuration;
            _httpClient = new HttpClient();
        }


        [HttpPost("refresh-schema")]
        public async Task<IActionResult> RefreshSchema([FromServices] SchemaCacheService schemaCacheService)
        {
            await schemaCacheService.RefreshSchemaCache();
            return Ok("Schema cache refreshed.");
        }



        [HttpPost("query")]
        public async Task<IActionResult> QueryDatabase([FromBody] QueryRequest request, [FromServices] SchemaCacheService schemaCacheService)
        {
            if (string.IsNullOrWhiteSpace(request.UserQuery))
                return BadRequest("Query cannot be empty.");

            try
            {
                // Step 1: Identify relevant tables
                var relevantTables = schemaCacheService.ExtractRelevantTables(request.UserQuery);

                if (relevantTables.Count == 0)
                    return BadRequest("No relevant tables found for the query.");

                // Step 2: Fetch schema details for relevant tables
                var minimalSchema = await schemaCacheService.GetRelevantSchema(relevantTables);

                // Step 3: Generate SQL using OpenAI
                string sqlQuery = await GenerateSQLQuery(request.UserQuery, minimalSchema);

                if (string.IsNullOrEmpty(sqlQuery))
                    return BadRequest("Failed to generate SQL query.");

                // Step 4: Execute SQL Query
                var result = await ExecuteSQLQuery(sqlQuery);
                return Ok(new { query = sqlQuery, data = result });
            }
            catch (Exception ex)
            {
                return StatusCode(500, new { error = ex.Message });
            }
        }

        private async Task<string> GenerateSQLQuery(string userQuery, string minimalSchema)
        {
            var apiKey = _configuration["AzureOpenAI:ApiKey"];
            var endpoint = _configuration["AzureOpenAI:Endpoint"];
            var deploymentId = _configuration["AzureOpenAI:DeploymentId"];

            string requestUrl = $"{endpoint}/openai/deployments/{deploymentId}/chat/completions?api-version=2023-06-01-preview";

            var requestBody = new
            {
                messages = new[]
                {
            //new { role = "system", content = "You are an expert in SQL query generation for Microsoft Azure SQL. Convert user questions into valid SQL queries using the provided schema. Follow these rules strictly:\n\n- Do NOT use 'USE' statements.\n- Ensure compatibility with Microsoft Azure SQL.\n- Use square brackets [ ] for table and column names.\n- Always generate optimized SQL queries with necessary joins.\n\n### Example SQL Queries:\n1. Find total sales last month:\n   SELECT SUM(OrderAmount) FROM [SalesOrder] WHERE [OrderDate] >= DATEADD(MONTH, -1, CAST(GETDATE() AS DATE)) AND [Deleted] = 0;\n\n2. Count total customers:\n   SELECT COUNT(*) FROM [buyer] WHERE [IsActive] = 1;\n\n### Database Schema:\n{minimalSchema}" },
            new { role = "system", content = "You are an expert in SQL query generation for Microsoft Azure SQL. Convert user questions into valid SQL queries using the provided schema. Do NOT use backticks (`) under any circumstances. Use square brackets [ ] for table and column names. Never ever create and execute the DML SQL statements like Create,Drop Update,Delete, only select statements must be created by you. " },
            new { role = "system", content = "### Guidelines:\\n- Do NOT include 'USE' statements.\\n- Ensure compatibility with Microsoft Azure SQL.\\n- Use square brackets [ ] for table and column names instead of backticks (`).\\n- Use 'CAST(GETDATE() AS DATE)' instead of 'EOMONTH()' for date comparisons.\\n- Ensure correct joins based on primary and foreign keys.\\n- Avoid unnecessary columns in SELECT statements." },
            new { role = "system", content = $"### Database Schema:\n{minimalSchema}" },
            new { role = "user", content = userQuery }
        },
                max_tokens = 150
            };

            var jsonRequest = JsonSerializer.Serialize(requestBody);
            var content = new StringContent(jsonRequest, System.Text.Encoding.UTF8, "application/json");

            _httpClient.DefaultRequestHeaders.Clear();
            _httpClient.DefaultRequestHeaders.Add("api-key", apiKey);

            var response = await _httpClient.PostAsync(requestUrl, content);
            var jsonResponse = await response.Content.ReadAsStringAsync();

            if (!response.IsSuccessStatusCode)
            {
                throw new Exception($"OpenAI API Error: {jsonResponse}");
            }

            var responseObject = JsonSerializer.Deserialize<OpenAIResponse>(jsonResponse, new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase
            });

            return responseObject?.Choices?[0]?.Message?.Content?.Trim() ?? string.Empty;
        }
        private async Task<List<Dictionary<string, object>>> ExecuteSQLQuery(string sqlQuery)
        {
            var connectionString = _configuration.GetConnectionString("AzureSQL");
            var resultList = new List<Dictionary<string, object>>();
            Console.WriteLine($"Generated SQL: {sqlQuery}");
            sqlQuery = sqlQuery.Replace("`", ""); // Remove backticks if OpenAI adds them
            Console.WriteLine($"Generated SQL: {sqlQuery}");
            using (SqlConnection conn = new SqlConnection(connectionString))
            {
                await conn.OpenAsync();
                using (SqlCommand cmd = new SqlCommand(sqlQuery, conn))
                {
                    using (SqlDataReader reader = await cmd.ExecuteReaderAsync())
                    {
                        while (await reader.ReadAsync())
                        {
                            var row = new Dictionary<string, object>();
                            for (int i = 0; i < reader.FieldCount; i++)
                            {
                                row[reader.GetName(i)] = reader.GetValue(i);
                            }
                            resultList.Add(row);
                        }
                    }
                }
            }
            return resultList;
        }
    }
}
