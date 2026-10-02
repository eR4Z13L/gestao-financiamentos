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
; (uma tela com tres campos opcionais, um por arquivo: planilha, admin_senha.json e
; service_account_admin.json) se a pessoa ja tem esses arquivos - cada um escolhido
; separadamente, de qualquer pasta - e o instalador copia cada um pro lugar certo
; ([Code] abaixo). Campo em branco = arquivo fica faltando, e o
; LEIA-ME-primeira-instalacao.txt explica o que fazer.
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
; O cliente OAuth ("App para computador") vai junto: ele so identifica o APP para o "Entrar com Google" (o
; Google trata esse tipo como publico) e nao da acesso a nada sozinho - quem da e a conta de cada pessoa.
; Vem de credentials\ deste PC (fora do git); sem ele, o login Google mostra erro explicando.
Source: "..\credentials\oauth_cliente_google.json"; DestDir: "{app}\credentials"; Flags: ignoreversion

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
const
  CAMPO_PLANILHA = 0;
  CAMPO_SENHA = 1;
  CAMPO_CHAVE = 2;

var
  PaginaArquivos: TInputFileWizardPage;

procedure InitializeWizard;
begin
  // uma tela, um campo (com o proprio botao "Procurar...") por arquivo: da pra juntar os tres
  // numa pasta qualquer (pendrive, Downloads) e escolher um por um, sem depender de estrutura de pasta
  PaginaArquivos := CreateInputFilePage(wpSelectDir,
    'Arquivos de uma instalação anterior (opcionais)',
    'Selecione cada arquivo que você já tem. O instalador copia cada um para o lugar certo.',
    'Deixe em branco o que você não tiver. Sem a planilha, o programa começa vazio; sem a senha, '
    + 'ele pede para criar uma senha nova de Administrador ao abrir; sem a chave do Google, '
    + 'funciona só neste computador, sem sincronizar com a nuvem.');
  PaginaArquivos.Add('Planilha de dados (controle_financiamentos.dat ou .xlsx):',
    'Planilha (*.dat, *.xlsx)|*.dat;*.xlsx|Todos os arquivos (*.*)|*.*', '');
  PaginaArquivos.Add('Senha do Administrador (admin_senha.json):',
    'Senha do Administrador (admin_senha.json)|admin_senha*.json|Arquivos JSON (*.json)|*.json|Todos os arquivos (*.*)|*.*', '');
  PaginaArquivos.Add('Chave do Google Sheets (service_account_admin.json):',
    'Chave do Google (*.json)|*.json|Todos os arquivos (*.*)|*.*', '');
end;

function ConteudoDe(Caminho: String): AnsiString;
begin
  Result := '';
  if not LoadStringFromFile(Caminho, Result) then
    Result := '';
end;

// Confere o arquivo de cada campo pelo CONTEUDO (nao pelo nome), pra pegar arquivo trocado de campo.
function ArquivoConfere(Campo: Integer; Caminho: String; var Motivo: String): Boolean;
var
  Conteudo: AnsiString;
begin
  Result := False;
  if not FileExists(Caminho) then
  begin
    Motivo := 'o arquivo indicado não existe';
    exit;
  end;
  Conteudo := ConteudoDe(Caminho);
  case Campo of
    CAMPO_PLANILHA:
      // .dat e .xlsx sao um .zip por dentro: sempre comecam com "PK"
      if Copy(Conteudo, 1, 2) <> 'PK' then
        Motivo := 'não parece ser a planilha do programa (.dat ou .xlsx)'
      else
        Result := True;
    CAMPO_SENHA:
      if Pos('senha_hash', Conteudo) = 0 then
        Motivo := 'não parece ser o arquivo de senha do Administrador (admin_senha.json)'
      else
        Result := True;
    CAMPO_CHAVE:
      if (Pos('service_account', Conteudo) = 0) or (Pos('private_key', Conteudo) = 0) then
        Motivo := 'não parece ser a chave do Google (service_account_admin.json)'
      else
        Result := True;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Campo: Integer;
  Motivo: String;
begin
  Result := True;
  if CurPageID <> PaginaArquivos.ID then
    exit;
  for Campo := CAMPO_PLANILHA to CAMPO_CHAVE do
    if (Trim(PaginaArquivos.Values[Campo]) <> '')
       and (not ArquivoConfere(Campo, Trim(PaginaArquivos.Values[Campo]), Motivo)) then
    begin
      MsgBox(PaginaArquivos.PromptLabels[Campo].Caption + #13#10#13#10 + 'O arquivo escolhido ' + Motivo
        + '. Escolha o arquivo certo ou deixe esse campo em branco.', mbError, MB_OK);
      Result := False;
      exit;
    end;
end;

procedure CopiarSeEscolhido(Campo: Integer; Destino, Nome: String);
var
  Origem: String;
begin
  Origem := Trim(PaginaArquivos.Values[Campo]);
  if Origem = '' then
    exit;
  if not CopyFile(Origem, ExpandConstant(Destino), False) then
    MsgBox('Não foi possível copiar ' + Nome + '. Copie manualmente depois (veja o LEIA-ME).', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    exit;
  CopiarSeEscolhido(CAMPO_PLANILHA, '{app}\data\controle_financiamentos.dat', 'a planilha');
  CopiarSeEscolhido(CAMPO_SENHA, '{app}\credentials\admin_senha.json', 'a senha do Administrador');
  CopiarSeEscolhido(CAMPO_CHAVE, '{app}\credentials\service_account_admin.json', 'a chave do Google');
end;
