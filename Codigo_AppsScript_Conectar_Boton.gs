const GITHUB_CONFIG = {
  USUARIO: "TU_USUARIO_DE_GITHUB",
  REPO: "remax-crm-bot",
  WORKFLOW_FILE: "busqueda_diaria.yml",
  TOKEN: "ghp_PEGA_AQUI_TU_TOKEN"
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🏢 RE/MAX CRM")
    .addItem("🚀 Buscar propiedades ahora (Chrome en la nube)", "ejecutarBusquedaDiaria")
    .addToUi();
}

function ejecutarBusquedaDiaria() {
  const url = `https://api.github.com/repos/${GITHUB_CONFIG.USUARIO}/${GITHUB_CONFIG.REPO}/actions/workflows/${GITHUB_CONFIG.WORKFLOW_FILE}/dispatches`;
  
  const options = {
    method: "post",
    headers: {
      "Authorization": `Bearer ${GITHUB_CONFIG.TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    contentType: "application/json",
    payload: JSON.stringify({ ref: "main" }),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  const code = response.getResponseCode();

  if (code === 204) {
    SpreadsheetApp.getUi().alert(
      "🚀 ¡Robot iniciado en la nube!\n\n" +
      "Chrome ya está buscando propiedades en remax.com.ar para todos tus clientes ACTIVOS.\n" +
      "En unos 60 segundos van a aparecer automáticamente en 'SUGERENCIAS DIARIAS'."
    );
  } else {
    SpreadsheetApp.getUi().alert(
      "⚠️ Error al conectar con GitHub (Código " + code + "):\n" + response.getContentText()
    );
  }
}
