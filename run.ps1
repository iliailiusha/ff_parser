Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
python goofish_parser\main.py
pause
