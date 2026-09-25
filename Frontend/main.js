const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 1100,
    minHeight: 700,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, "src", "index.html"));
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

ipcMain.handle("show-open-file-dialog", async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options.title || "Select document",
    properties: ["openFile"],
    filters: options.filters || [
      { name: "PDF", extensions: ["pdf"] },
      { name: "Documents", extensions: ["pdf", "doc", "docx", "txt", "xlsx", "xls"] },
      // Extensionless PDFs (e.g. Downloads saved without .pdf) appear here
      { name: "All Files", extensions: ["*"] }
    ]
  });
  if (result.canceled || !result.filePaths.length) {
    return null;
  }
  const filePath = result.filePaths[0];
  let name = path.basename(filePath);
  // Backend / dialogs expect a .pdf suffix; many downloads omit it.
  if (!path.extname(name)) {
    name = `${name}.pdf`;
  }
  return {
    path: filePath,
    name
  };
});
