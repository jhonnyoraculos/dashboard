@echo off
title Atualizar projeto JR Dashboard
color 0a

echo ============================================
echo  Atualizando e enviando para o GitHub
echo  (commita tudo que estiver alterado)
echo ============================================
echo.

REM Muda para a pasta onde este .bat esta, garantindo o repo correto
cd /d "%~dp0"

REM Ativa o ambiente virtual (se tiver)
if exist venv\Scripts\activate (
    call venv\Scripts\activate
)

REM Mostra status
git status -sb
echo.

REM Adiciona todas as mudancas (inclui planilhas)
git add .

REM Cria commit com data e hora
set hora=%time:~0,2%:%time:~3,2%
set hora=%hora: =0%
set data=%date:~-4%-%date:~3,2%-%date:~0,2%
git commit -m "Atualizacao automatica %data% %hora%"

REM Puxa alteracoes do GitHub antes de enviar
git pull origin main --rebase

REM Envia pro GitHub
git push origin main

echo.
echo ============================================
echo  Pronto. Atualizacao enviada ao GitHub.
echo ============================================
echo.
pause
