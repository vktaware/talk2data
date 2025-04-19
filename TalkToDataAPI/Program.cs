using Microsoft.Extensions.Caching.Memory;
using TalkToDataAPI.Services;

namespace TalkToDataAPI
{
    public class Program
    {
        public static void Main(string[] args)
        {
          

            var builder = WebApplication.CreateBuilder(args);

            // Add services to the DI container
            builder.Services.AddControllers();
            builder.Services.AddEndpointsApiExplorer();
            builder.Services.AddSwaggerGen();
            builder.Services.AddSingleton<SchemaCacheService>();

            // Register MemoryCache
            builder.Services.AddMemoryCache();
            var apiKey = builder.Configuration["AzureOpenAI:ApiKey"];
            if (string.IsNullOrEmpty(apiKey))
            {
                throw new Exception("Azure OpenAI API Key is missing! Check appsettings.json.");
            }

            builder.Services.AddCors(options =>
            {
                options.AddPolicy("AllowReactApp",
                    builder => builder.WithOrigins("http://localhost:3000")
                                      .AllowAnyHeader()
                                      .AllowAnyMethod());
            });

            var app = builder.Build();
            app.UseCors("AllowReactApp");


            // Ensure schema is cached at startup
            using (var scope = app.Services.CreateScope())
            {
                var schemaService = scope.ServiceProvider.GetRequiredService<SchemaCacheService>();
                schemaService.InitializeSchemaCache().Wait();
            }

            app.UseAuthorization();
            app.MapControllers();
            app.UseSwagger();
            app.UseSwaggerUI();

            app.Run();


        }
    }
}
