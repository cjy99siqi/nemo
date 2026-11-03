' OilLab 启动器：双击运行，不显示控制台窗口
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)

On Error Resume Next
sh.Run "pythonw oil_monitor_gui.py", 0, False
If Err.Number <> 0 Then
    Err.Clear
    sh.Run "pyw -3 oil_monitor_gui.py", 0, False
End If
If Err.Number <> 0 Then
    Err.Clear
    sh.Run "python oil_monitor_gui.py", 0, False
End If
If Err.Number <> 0 Then
    MsgBox "未找到 Python，请先安装 Python 3.9+（安装时勾选 Add to PATH）", 16, "OilLab"
End If
