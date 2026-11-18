' Run "python.exe main.py --once" with a hidden console window (scheduled task GamesParser).
' A visible console from the task used to steal focus and throw fullscreen games to the desktop.
' pythonw.exe is not an option: src/common/logger.py writes to sys.stdout.fileno().
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
WScript.Quit sh.Run("""" & dir & "\.venv\Scripts\python.exe"" main.py --once", 0, True)
