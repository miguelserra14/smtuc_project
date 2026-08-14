<#
Corre a stack toda do FeedNPlay num só comando - substitui o processo manual de 3 terminais
(Docker Compose do Kafka, produtor de amostra do devkit, bridge.py) por este script.

O que faz, por ordem:
    1. Confirma que o devkit (feednplay_devkit) está clonado ao lado do projeto.
    2. Confirma que o Docker Desktop está a correr.
    3. Sobe Kafka + Zookeeper (docker compose up -d - idempotente, não recria se já estiverem
       a correr de uma execução anterior).
    4. Espera que o broker Kafka fique mesmo pronto a responder (não só o container "up").
    5. Arranca o produtor de amostra (top_cam_sample.mp4, em loop infinito) em segundo plano,
       com o output redirecionado para um ficheiro de log.
    6. Abre o bridge.py (janela pywebview) em primeiro plano - é a janela que vês e testas.
    7. Ao fechares essa janela (ou Ctrl+C), o produtor em segundo plano é sempre terminado.
       O Kafka fica a correr entre execuções (a próxima vez é mais rápida), a menos que
       passes -StopKafka.

Uso:
    .\scripts\test_feednplay_local.ps1                    # janela pequena (1280x720), sem preview
    .\scripts\test_feednplay_local.ps1 -Preview           # produtor também mostra as janelas de debug (OpenCV)
    .\scripts\test_feednplay_local.ps1 -FullWall          # bridge a 9720x1920 (tamanho real da parede)
    .\scripts\test_feednplay_local.ps1 -Regenerate        # corre regenerate_all_htmls.py primeiro
    .\scripts\test_feednplay_local.ps1 -StopKafka         # ao sair, também pára os containers Docker

Nota: para uma paragem limpa, fecha a janela do bridge em vez de Ctrl+C no terminal - o
Ctrl+C pode não deixar correr sempre a limpeza do produtor em segundo plano.
#>
param(
    [switch]$Preview,
    [switch]$FullWall,
    [switch]$StopKafka,
    [switch]$Regenerate
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DevkitRoot = Join-Path (Split-Path -Parent $ProjectRoot) "feednplay_devkit"
$ComposeFile = Join-Path $DevkitRoot "data_streaming\docker-compose.yaml"
$ProducerScript = Join-Path $DevkitRoot "data_streaming\examples_of_data_producers\produce_cam_top_data_in_python\produce_cam_top_data.py"
$SampleVideo = Join-Path $DevkitRoot "data_streaming\examples_of_data_producers\produce_cam_top_data_in_python\top_cam_sample.mp4"
$PythonExe = "C:\Users\migue\miniconda3\envs\smtuc312\python.exe"
$BridgeScript = Join-Path $ProjectRoot "src\feednplay\bridge.py"
$DashboardHtml = Join-Path $ProjectRoot "outputs\feednplay_dashboard.html"
$LogDir = Join-Path $ProjectRoot "scripts\.feednplay_logs"
$ProducerLog = Join-Path $LogDir "producer.log"
$ProducerErrLog = Join-Path $LogDir "producer.err.log"
$PidFile = Join-Path $LogDir "producer.pid"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Stop-SampleProducer {
    if (Test-Path $PidFile) {
        $existingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($existingPid) {
            $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "[INFO] A parar o produtor de amostra (PID $existingPid)..."
                Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ForKafka {
    Write-Host "[INFO] A espera que o broker Kafka fique pronto..."
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        docker exec broker kafka-topics --bootstrap-server localhost:9092 --list *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Kafka pronto."
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

# --------------------------------------------------------------------------------------
# 1. Devkit presente?
foreach ($p in @($ComposeFile, $ProducerScript, $SampleVideo)) {
    if (-not (Test-Path $p)) {
        Write-Error "Nao encontrado: $p`nConfirma que o feednplay_devkit esta clonado em: $DevkitRoot"
        exit 1
    }
}

# 2. Dashboard gerado?
if (-not (Test-Path $DashboardHtml)) {
    if ($Regenerate) {
        Write-Host "[INFO] outputs\feednplay_dashboard.html nao existe - a regenerar (pode demorar)..."
        Push-Location $ProjectRoot
        $env:PYTHONPATH = "$ProjectRoot;$ProjectRoot\src"
        & $PythonExe "src\tests\regenerate_all_htmls.py"
        Pop-Location
        if (-not (Test-Path $DashboardHtml)) {
            Write-Error "Regeneracao correu mas outputs\feednplay_dashboard.html continua em falta - ver output acima."
            exit 1
        }
    } else {
        Write-Error "outputs\feednplay_dashboard.html nao existe. Corre com -Regenerate, ou manualmente:`n  python src\tests\regenerate_all_htmls.py"
        exit 1
    }
}

# 3. Docker Desktop a correr?
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Desktop nao esta a correr (ou nao esta acessivel). Abre o Docker Desktop e tenta novamente."
    exit 1
}

# 4. Kafka + Zookeeper (idempotente)
Write-Host "[INFO] A subir Kafka + Zookeeper (docker compose up -d)..."
docker compose -f $ComposeFile up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up falhou - ver output acima."
    exit 1
}

if (-not (Wait-ForKafka)) {
    Write-Error "Kafka nao ficou pronto em 60s - confirma com: docker compose -f `"$ComposeFile`" logs"
    exit 1
}

# 5. Produtor de amostra em segundo plano (mata qualquer instancia de uma execucao anterior
# esquecida a correr, para nao publicar dois fluxos em simultaneo no mesmo topico).
Stop-SampleProducer

Write-Host "[INFO] A arrancar o produtor de amostra em segundo plano (log: $ProducerLog)..."
# String unica (nao array) - com um array, Start-Process -ArgumentList nao entre-aspas
# elementos com espacos (o caminho tem "side quests"), e o Python via cada palavra como um
# argumento a parte, falhando a abrir o ficheiro.
$producerArgString = "`"$ProducerScript`" --sample `"$SampleVideo`""
if ($Preview) { $producerArgString += " --preview" }

$producerProc = Start-Process -FilePath $PythonExe -ArgumentList $producerArgString `
    -WorkingDirectory (Split-Path $ProducerScript) `
    -RedirectStandardOutput $ProducerLog -RedirectStandardError $ProducerErrLog `
    -PassThru -WindowStyle Hidden
$producerProc.Id | Out-File -FilePath $PidFile -Encoding ascii

Start-Sleep -Seconds 2
if ($producerProc.HasExited) {
    Write-Error "O produtor de amostra fechou logo a seguir a arrancar - ve o log: $ProducerLog / $ProducerErrLog"
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    exit 1
}

# 6. Bridge (janela pywebview) em primeiro plano - é a janela que se testa.
try {
    Write-Host "[INFO] A abrir o bridge (fecha esta janela para terminar o teste)..."
    if ($FullWall) {
        & $PythonExe $BridgeScript --x 0 --y 0 --w 9720 --h 1920
    } else {
        & $PythonExe $BridgeScript --x 100 --y 100 --w 1280 --h 720
    }
} finally {
    # 7. Limpeza - o produtor em segundo plano nunca deve ficar orfao.
    Stop-SampleProducer
    if ($StopKafka) {
        Write-Host "[INFO] A parar os containers Docker (docker compose down)..."
        docker compose -f $ComposeFile down
    } else {
        Write-Host "[INFO] Kafka continua a correr (usa -StopKafka para tambem parar os containers)."
    }
}
