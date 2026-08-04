@echo off
D:\freecad\bin\freecadcmd.exe -c "exec(open(r'D:\project_main\NL-FreeCAD-Agent\freecad_addon\AICADAgent\tests\test_all_tools_smoke.py', encoding='utf-8').read())"
echo EXITCODE=%ERRORLEVEL%
