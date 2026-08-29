' Iniciar VideoMaker.vbs
' ----------------------
' Abre "VideoMaker Automatico" sin ventana negra de CMD.
'
' Antes de abrirlo mete la carpeta "bin" (que trae ffmpeg y ffprobe) al
' PATH de este proceso. Asi el programa los encuentra aunque en esta PC
' no este instalado ffmpeg, y sin tener que tocar nada del codigo.

Option Explicit

Dim fso, sh, carpeta, exePython, app, env

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

carpeta = fso.GetParentFolderName(WScript.ScriptFullName)
app     = carpeta & "\videomaker.pyw"

If Not fso.FileExists(app) Then
    MsgBox "No encuentro 'videomaker.pyw'." & vbCrLf & vbCrLf & _
           "Descomprime el RAR completo y abre el acceso directo desde ahi," & vbCrLf & _
           "sin sacar archivos sueltos de la carpeta.", _
           16, "VideoMaker Automatico"
    WScript.Quit 1
End If

' --- ffmpeg incluido: se pone de primero en el PATH ---------------------
Set env = sh.Environment("PROCESS")
env("PATH") = carpeta & "\bin;" & env("PATH")

' --- Buscar el Python "sin consola" -------------------------------------
exePython = BuscarPythonw(fso, sh)

If exePython = "" Then
    MsgBox "No encuentro Python en esta PC." & vbCrLf & vbCrLf & _
           "Instalalo desde:  https://www.python.org/downloads/" & vbCrLf & _
           "IMPORTANTE: marca la casilla ""Add Python to PATH"" al instalar." & vbCrLf & vbCrLf & _
           "Despues vuelve a abrir este acceso directo.", _
           16, "VideoMaker Automatico"
    WScript.Quit 1
End If

sh.CurrentDirectory = carpeta
sh.Run """" & exePython & """ """ & app & """", 0, False


' ------------------------------------------------------------------------
Function BuscarPythonw(fso, sh)
    Dim candidatos, ruta, i, base, carp, sub_, bases

    candidatos = Array( _
        sh.ExpandEnvironmentStrings("%WINDIR%\pyw.exe"), _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Launcher\pyw.exe"), _
        sh.ExpandEnvironmentStrings("%PROGRAMFILES%\Python\Launcher\pyw.exe") )

    For i = 0 To UBound(candidatos)
        If fso.FileExists(candidatos(i)) Then
            BuscarPythonw = candidatos(i)
            Exit Function
        End If
    Next

    ' Buscar pythonw.exe dentro de las instalaciones tipicas de Python
    bases = Array( _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python"), _
        sh.ExpandEnvironmentStrings("%PROGRAMFILES%"), _
        sh.ExpandEnvironmentStrings("%PROGRAMFILES(X86)%") )

    For i = 0 To UBound(bases)
        base = bases(i)
        If fso.FolderExists(base) Then
            Set carp = fso.GetFolder(base)
            For Each sub_ In carp.SubFolders
                If LCase(Left(sub_.Name, 6)) = "python" Then
                    ruta = sub_.Path & "\pythonw.exe"
                    If fso.FileExists(ruta) Then
                        BuscarPythonw = ruta
                        Exit Function
                    End If
                End If
            Next
        End If
    Next

    ' Ultimo intento: que este en el PATH
    On Error Resume Next
    Dim r
    r = sh.Run("cmd /c where pythonw.exe", 0, True)
    If Err.Number = 0 And r = 0 Then
        BuscarPythonw = "pythonw.exe"
        Exit Function
    End If
    On Error GoTo 0

    BuscarPythonw = ""
End Function
