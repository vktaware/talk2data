import React, { useState } from "react";
import { Box, TextField, IconButton, CircularProgress, Typography, Paper } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import SmartToyIcon from "@mui/icons-material/SmartToy"; // AI Assistant Icon
import "@fontsource/inter"; // Importing Inter font
import botIcon from './assets/robot.png';

const API_BASE_URL = "https://localhost:7197/api/TalkToData"; // Update with your API URL

const sampleQueries = [
    "What is total sales last month?",
    "How many orders we received last month?",
    "What are top 5 top-selling products?",
    "Show pending orders for this week.",
];



const TalkToData = () => {
    const [messages, setMessages] = useState([
        { text: "Hello! How can I assist you today?", isUser: false }
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSend = async (query) => {
        const userMessage = query || input.trim();
        if (userMessage === "") return;

        setMessages([...messages, { text: userMessage, isUser: true }]);
        setInput("");
        setLoading(true);

        try {
            const response = await fetch(`${API_BASE_URL}/query`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ UserQuery: userMessage })
            });

            const data = await response.json();
            let resultComponent = "No data available";

            if (data.data && data.data.length > 0) {
                const firstRow = data.data[0];

                if (data.data.length === 1 && Object.keys(firstRow).length === 1) {
                    // Case 1: Single-word or single-value response
                    resultComponent = <Typography>{Object.values(firstRow)[0].toString()}</Typography>;
                } 
                else if (data.data.length === 1 && Object.keys(firstRow).length > 1) {
                    // Case 2: Single row with multiple columns → Show key-value pairs as text
                    resultComponent = (
                        <Box>
                            {Object.entries(firstRow).map(([key, value]) => (
                                <Typography key={key}><strong>{key}:</strong> {value}</Typography>
                            ))}
                        </Box>
                    );
                } 
                else {
                    // Case 3: Multiple rows → Render as a table
                    resultComponent = (
                        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: "10px", color: "#fff" }}>
                            <thead>
                                <tr>
                                    {Object.keys(firstRow).map((key) => (
                                        <th key={key} style={{ border: "1px solid #ddd", padding: "8px", backgroundColor: "#00509E" }}>
                                            {key}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {data.data.map((row, index) => (
                                    <tr key={index}>
                                        {Object.values(row).map((value, colIndex) => (
                                            <td key={colIndex} style={{ border: "1px solid #ddd", padding: "8px" }}>
                                                {value}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    );
                }
            }

            setMessages((prev) => [...prev, { text: resultComponent, isUser: false, isTable: Array.isArray(resultComponent) }]);
        } catch (error) {
            console.error("Error fetching data:", error);
            setMessages((prev) => [...prev, { text: "Error processing request.", isUser: false }]);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Box sx={{
            width: "90%",
            maxWidth: "1200px",
            margin: "auto",
            padding: "20px",
            backgroundColor: "#001F3F",
            borderRadius: "12px",
            color: "#fff",
            minHeight: "80vh",
            display: "flex",
            flexDirection: "column",
            fontFamily: "'Inter', sans-serif" // Applying Inter Font Globally
        }}>
            {/* Chat Messages */}
            <Box sx={{ flex: 1, overflowY: "auto", paddingBottom: "10px", display: "flex", flexDirection: "column" }}>
                {messages.map((msg, index) => (
                    <Box 
                        key={index} 
                        sx={{ 
                            display: "flex", 
                            justifyContent: msg.isUser ? "flex-end" : "flex-start", 
                            alignItems: "center", 
                            marginBottom: "10px"
                        }}
                    >
                        {!msg.isUser && <img src={botIcon} alt="Bot" style={{ width: "30px", height: "30px", marginRight: "8px" }} />}

                        <Paper 
                            elevation={3}
                            sx={{
                                padding: "12px 16px",
                                borderRadius: msg.isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                                backgroundColor: msg.isUser ? "#007BFF" : "#003366",
                                color: "#fff",
                                maxWidth: "70%",
                                fontFamily: "'Inter', sans-serif", // Apply Inter font
                                fontSize: "16px", // Slightly bigger text
                                position: "relative",
                                "&::before": {
                                    content: '""',
                                    position: "absolute",
                                    bottom: "-6px",
                                    left: msg.isUser ? "auto" : "10px",
                                    right: msg.isUser ? "10px" : "auto",
                                    borderWidth: "6px",
                                    borderStyle: "solid",
                                    borderColor: msg.isUser 
                                        ? "#007BFF transparent transparent transparent" 
                                        : "#003366 transparent transparent transparent"
                                }
                            }}
                        >
                            {msg.isTable ? msg.text : <Typography>{msg.text}</Typography>}
                        </Paper>
                        {msg.isUser && <AccountCircleIcon sx={{ color: "#4CAF50", marginLeft: "8px" }} />} {/* User Icon */}
                    </Box>
                ))}
                {loading && <CircularProgress color="inherit" size={24} sx={{ marginLeft: "10px" }} />}
            </Box>

            {/* Sample Queries */}
            <Box sx={{
                display: "flex",
                justifyContent: "center",
                gap: "12px",
                padding: "10px",
                flexWrap: "wrap",
                borderTop: "2px solid #004080"
            }}>
                {sampleQueries.map((query, index) => (
                    <Paper 
                        key={index} 
                        elevation={2} 
                        onClick={() => handleSend(query)}
                        sx={{
                            padding: "8px 12px",
                            borderRadius: "8px",
                            backgroundColor: "#002B5B",
                            color: "#fff",
                            cursor: "pointer",
                            transition: "background 0.2s",
                            fontFamily: "'Inter', sans-serif",
                            fontSize: "14px",
                            "&:hover": { backgroundColor: "#00509E" }
                        }}
                    >
                        {query}
                    </Paper>
                ))}
            </Box>

            {/* Input Field */}
            <Box sx={{ display: "flex", alignItems: "center", borderTop: "2px solid #004080", padding: "10px" }}>
                <TextField
                    fullWidth
                    variant="outlined"
                    placeholder="Ask about your data..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyPress={(e) => e.key === "Enter" && handleSend()}
                    sx={{ backgroundColor: "#fff", borderRadius: "8px", fontFamily: "'Inter', sans-serif" }}
                />
                <IconButton onClick={() => handleSend()} color="primary">
                    <SendIcon />
                </IconButton>
            </Box>

            {/* OrderIQ Data Lens Title (Bottom Center) */}
            <Box sx={{
                textAlign: "center",
                padding: "16px",
                fontSize: "18px",
                fontWeight: "bold",
                color: "#fff",
                backgroundColor: "#002B5B",
                marginTop: "20px",
                borderRadius: "8px"
            }}>
                OrderIQ Data Lens
            </Box>
        </Box>
    );
};

export default TalkToData;
