const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");

let mainWindow;

// The GNOME portal file chooser cancels Electron's request immediately on this desktop;
// forcing the built-in GTK dialog keeps document upload working.
if (process.platform === "linux") {
  app.commandLine.appendSwitch("xdg-portal-required-version", "999");
}

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

ipcMain.handle("show-open-files-dialog", async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options.title || "Select documents",
    properties: ["openFile", "multiSelections"],
    filters: options.filters || [{ name: "All Files", extensions: ["*"] }]
  });
  if (result.canceled || !result.filePaths.length) {
    return [];
  }
  return result.filePaths.map((filePath) => ({ path: filePath, name: path.basename(filePath) }));
});

ipcMain.handle("show-open-folder-dialog", async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options.title || "Select folder",
    properties: ["openDirectory"]
  });
  if (result.canceled || !result.filePaths.length) {
    return null;
  }
  return { path: result.filePaths[0], name: path.basename(result.filePaths[0]) };
});
