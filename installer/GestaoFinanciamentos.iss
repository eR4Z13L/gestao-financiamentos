; Script do Inno Setup (https://jrsoftware.org/isinfo.php) pra gerar o instalador do app.
;
; O QUE O INSTALADOR FAZ: copia o .exe (ja gerado pelo PyInstaller, em dist\) pra
; %LocalAppData%\Programs\GestaoFinanciamentos - pasta do PROPRIO usuario, sem pedir
; permissao de administrador (PrivilegesRequired=lowest) - e cria as pastas vazias
; "data" e "credentials" do lado. Cria atalho no Menu Iniciar e, se marcado, na
; Area de Trabalho.
;
; O QUE ELE NAO FAZ (de proposito): nao embute a planilha real nem as credenciais
; do Google DENTRO do .exe do instalador (isso ficaria fixo pra sempre num arquivo
; que pode ser copiado/enviado por engano). Em vez disso, o assistente PERGUNTA
; (duas telas, ambas opcionais) se a pessoa ja tem esses arquivos de uma instalacao
; anterior/backup - se sim, aponta o caminho e o instalador copia sozinho ([Code]
; abaixo). Se deixar em branco (primeira instalacao mesmo, do zero), fica igual a
; antes: pastas vazias, e o LEIA-ME-primeira-instalacao.txt explica o que falta.
;
; COMO GERAR O INSTALADOR (depois de ter o Inno Setup instalado):
;   1. Gere o .exe normal do app (pyinstaller GestaoFinanciamentos.spec) - o
;      instalador espera achar dist\GestaoFinanciamentos.exe.
;   2. Compile este script: iscc installer\GestaoFinanciamentos.iss
;   3. O instalador pronto aparece em installer\saida\GestaoFinanciamentos-Setup.exe
;
; Ao lancar uma versao nova: atualize AppVersion abaixo pro MESMO valor de
; config.VERSAO_APP (sao dois lugares porque o Inno Setup nao le arquivo .py).

#define MyAppName "Gestão de Financiamentos"
#define MyAppVersion "1.0.0"
#define MyAppExeName "GestaoFinanciamentos.exe"

[Setup]
AppId={{5BC133A3-8FD3-4BD6-BA3E-8C9D2F43EA0C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\GestaoFinanciamentos
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=saida
OutputBaseFilename=GestaoFinanciamentos-Setup
SetupIconFile=..\desktop\assets\icone_app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEIA-ME-primeira-instalacao.txt"; DestDir: "{app}"; Flags: ignoreversion

; pastas vazias, prontas pra receber a planilha real e as credenciais (copiadas a
; mao depois - ver LEIA-ME-primeira-instalacao.txt). Nunca apagadas no desinstalar
; (nao entram em [UninstallDelete]) - desinstalar/reinstalar pra atualizar a versao
; NUNCA pode arriscar os dados reais de quem ja usa o programa.
[Dirs]
Name: "{app}\data"
Name: "{app}\credentials"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName} agora"; Flags: postinstall nowait skipifsilent
Filename: "{win}\notepad.exe"; Parameters: """{app}\LEIA-ME-primeira-instalacao.txt"""; Description: "Ver o que falta copiar (planilha e credenciais)"; Flags: postinstall skipifsilent

[Code]
var
  PaginaPlanilha: TInputFileWizardPage;
  PaginaCredenciais: TInputDirWizardPage;

procedure InitializeWizard;
begin
  PaginaPlanilha := CreateInputFilePage(wpSelectDir,
    'Planilha de dados (opcional)',
    'Você já tem a planilha de uma instalação anterior ou de um backup?',
    'Se já tem o arquivo "controle_financiamentos.dat" (ou ainda ".xlsx", de antes da troca de '
    + 'extensão), selecione ele abaixo - o instalador copia pra pasta certa sozinho, já com o '
    + 'nome certo. Se esta é a primeira instalação, do zero, deixe em branco e clique em Avançar.');
  PaginaPlanilha.Add('Arquivo da planilha:',
    'Planilha (*.dat, *.xlsx)|*.dat;*.xlsx|Todos os arquivos (*.*)|*.*', '');

  PaginaCredenciais := CreateInputDirPage(PaginaPlanilha.ID,
    'Credenciais de acesso (opcional)',
    'Você já tem a pasta "credentials" de uma instalação anterior ou de um backup?',
    'Se já tem essa pasta (com "admin_senha.json" e/ou "service_account_admin.json" dentro), '
    + 'selecione ela abaixo - o instalador copia os arquivos sozinho. Se esta é a primeira '
    + 'instalação, deixe em branco - o programa pede pra você definir uma senha nova de '
    + 'Administrador na primeira vez que abrir.',
    False, '');
  PaginaCredenciais.Add('');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = PaginaPlanilha.ID) and (PaginaPlanilha.Values[0] <> '')
     and (not FileExists(PaginaPlanilha.Values[0])) then
  begin
    MsgBox('O arquivo indicado não existe. Corrija o caminho ou deixe em branco.', mbError, MB_OK);
    Result := False;
  end
  else if (CurPageID = PaginaCredenciais.ID) and (PaginaCredenciais.Values[0] <> '')
     and (not DirExists(PaginaCredenciais.Values[0])) then
  begin
    MsgBox('A pasta indicada não existe. Corrija o caminho ou deixe em branco.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OrigemPlanilha, OrigemCredenciais: String;
  AchouAlgumaCredencial: Boolean;
begin
  if CurStep <> ssPostInstall then
    exit;

  OrigemPlanilha := PaginaPlanilha.Values[0];
  if OrigemPlanilha <> '' then
  begin
    if not CopyFile(OrigemPlanilha, ExpandConstant('{app}\data\controle_financiamentos.dat'), False) then
      MsgBox('Não foi possível copiar a planilha selecionada. Copie manualmente depois pra pasta "data".',
        mbError, MB_OK);
  end;

  OrigemCredenciais := PaginaCredenciais.Values[0];
  if OrigemCredenciais <> '' then
  begin
    AchouAlgumaCredencial := False;
    if FileExists(OrigemCredenciais + '\admin_senha.json') then
    begin
      CopyFile(OrigemCredenciais + '\admin_senha.json', ExpandConstant('{app}\credentials\admin_senha.json'), False);
      AchouAlgumaCredencial := True;
    end;
    if FileExists(OrigemCredenciais + '\service_account_admin.json') then
    begin
      CopyFile(OrigemCredenciais + '\service_account_admin.json',
        ExpandConstant('{app}\credentials\service_account_admin.json'), False);
      AchouAlgumaCredencial := True;
    end;
    if not AchouAlgumaCredencial then
      MsgBox('A pasta selecionada não tinha "admin_senha.json" nem "service_account_admin.json". '
        + 'Nada foi copiado - copie manualmente depois.', mbError, MB_OK);
  end;
end;
