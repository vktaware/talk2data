import React from "react";
import TalkToData from "./TalkToData";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const theme = createTheme({
    palette: {
        primary: { main: "#007BFF" },
        background: { default: "#001F3F" },
    },
    typography: {
        fontFamily: "Arial, sans-serif",
    },
});

function App() {
    return (
        <ThemeProvider theme={theme}>
            <TalkToData />
        </ThemeProvider>
    );
}

export default App;
