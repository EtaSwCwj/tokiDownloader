Option Explicit

Dim shell, fileSystem, root, pythonw, app, setup
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

root = fileSystem.GetParentFolderName(WScript.ScriptFullName)
pythonw = fileSystem.BuildPath(root, ".venv\Scripts\pythonw.exe")
app = fileSystem.BuildPath(root, "toki_launcher.py")
setup = fileSystem.BuildPath(root, "setup-gui.cmd")

If Not fileSystem.FileExists(pythonw) Then
    shell.Run Chr(34) & setup & Chr(34), 1, True
End If

If fileSystem.FileExists(pythonw) Then
    shell.CurrentDirectory = root
    shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & app & Chr(34) & " launch", 0, False
Else
    MsgBox "GUI environment is missing. Run setup-gui.cmd and check the error.", 16, "tokiDownloader"
End If
