@echo off
title Atualizar projeto JR Dashboard
color 0a

echo ============================================
echo  Atualizando o projeto e enviando ao GitHub
echo ============================================
echo.

REM Muda pra pasta do projeto
cd /d "C:\Users\jrferragens\OneDrive - JR Ferragens & Madeiras\01.HTML\DASHBOARD COMBUSTIVEL\DASHBOARD"

REM Ativa o ambiente virtual (se tiver)
if exist venv\Scripts\activate (
    call venv\Scripts\activate
)

REM Mostra status
git status
echo.

REM Adiciona todas as mudanças
git add .

REM Cria commit com data e hora
set hora=%time:~0,2%:%time:~3,2%
set data=%date:~-4%-%date:~3,2%-%date:~0,2%
git commit -m "Atualização automática %data% %hora%"

REM Puxa alterações do GitHub antes de enviar
git pull origin main --rebase

REM Envia pro GitHub
git push origin main

echo.
echo ============================================
echo  ✅ Atualização concluída com sucesso!
echo ============================================
echo.
pause
