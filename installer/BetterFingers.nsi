Unicode True

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"

!define APP_NAME "BetterFingers"
!define APP_VERSION "1.0"
!define APP_PUBLISHER "BetterFingers Team"
!define APP_EXE "BetterFingers.exe"
!define APP_ICON "$INSTDIR\_internal\images\BetterFingers.ico"
!define APP_REG_KEY "Software\BetterFingers"
!define UNINSTALL_REG_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\BetterFingers"
!define INNO_UNINSTALL_REG_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\BetterFingers_is1"

Name "${APP_NAME}"
OutFile "..\dist\BetterFingers_Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\BetterFingers"
InstallDirRegKey HKCU "${APP_REG_KEY}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ShowInstDetails show
ShowUninstDetails show

Var QuietUninstallString

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch BetterFingers"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  Call KillRunningProcesses
  Call UninstallPreviousVersion
FunctionEnd

Function KillRunningProcesses
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM BetterFingers.exe /F'
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM llama-server.exe /F'
  Sleep 900
FunctionEnd

Function UninstallPreviousVersion
  ; Prior NSIS install
  ReadRegStr $QuietUninstallString HKCU "${UNINSTALL_REG_KEY}" "QuietUninstallString"
  ${If} $QuietUninstallString != ""
    DetailPrint "Removing previous BetterFingers installation..."
    ExecWait '$QuietUninstallString' $0
    Sleep 900
  ${EndIf}

  ; Prior Inno Setup install (HKCU)
  ReadRegStr $0 HKCU "${INNO_UNINSTALL_REG_KEY}" "UninstallString"
  ${If} $0 != ""
    DetailPrint "Removing previous Inno Setup install (HKCU)..."
    ExecWait '$0 /VERYSILENT /SUPPRESSMSGBOXES /NORESTART' $1
    Sleep 900
  ${EndIf}

  ; Prior Inno Setup install (HKLM)
  ReadRegStr $0 HKLM "${INNO_UNINSTALL_REG_KEY}" "UninstallString"
  ${If} $0 != ""
    DetailPrint "Removing previous Inno Setup install (HKLM)..."
    ExecWait '$0 /VERYSILENT /SUPPRESSMSGBOXES /NORESTART' $1
    Sleep 900
  ${EndIf}
FunctionEnd

Section "BetterFingers (required)" SEC_MAIN
  SectionIn RO
  SetShellVarContext current
  Call KillRunningProcesses

  ; Ensure stale files from older builds are removed before copy.
  RMDir /r "$INSTDIR"
  CreateDirectory "$INSTDIR"
  SetOutPath "$INSTDIR"
  File /r "..\dist\BetterFingers\*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\BetterFingers"
  CreateShortcut "$SMPROGRAMS\BetterFingers\BetterFingers.lnk" "$INSTDIR\${APP_EXE}" "" "${APP_ICON}"
  CreateShortcut "$SMPROGRAMS\BetterFingers\Uninstall BetterFingers.lnk" "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "${APP_REG_KEY}" "InstallDir" "$INSTDIR"

  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "DisplayIcon" "${APP_ICON}"
  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_REG_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_REG_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_REG_KEY}" "NoRepair" 1
SectionEnd

Section /o "Desktop shortcut" SEC_DESKTOP
  SetShellVarContext current
  CreateShortcut "$DESKTOP\BetterFingers.lnk" "$INSTDIR\${APP_EXE}" "" "${APP_ICON}"
SectionEnd

Section /o "Start with Windows" SEC_STARTUP
  SetShellVarContext current
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "BetterFingers" '"$INSTDIR\${APP_EXE}"'
SectionEnd

SectionGroup /e "First-time model prefetch (optional)" SEC_MODEL_PREFETCH
Section /o "Recommended MVP pack (Gemma 3 4B Q4 + Whisper base.en + Kokoro TTS)" SEC_MODEL_PREFETCH_MVP
  SetShellVarContext current
  DetailPrint "Prefetching recommended starter models (this can take several minutes)..."
  nsExec::ExecToLog '"$INSTDIR\${APP_EXE}" --prefetch-mvp --log-level INFO'
SectionEnd

Section /o "LLM only: Gemma 3 4B Q4" SEC_MODEL_PREFETCH_LLM_Q4
  SetShellVarContext current
  DetailPrint "Prefetching LLM model Gemma 3 4B Q4..."
  nsExec::ExecToLog '"$INSTDIR\${APP_EXE}" --prefetch-llm-model gemma-3-4b-q4 --log-level INFO'
SectionEnd

Section /o "Whisper only: base.en" SEC_MODEL_PREFETCH_WHISPER_BASE
  SetShellVarContext current
  DetailPrint "Prefetching Whisper model base.en..."
  nsExec::ExecToLog '"$INSTDIR\${APP_EXE}" --prefetch-whisper-model base.en --log-level INFO'
SectionEnd

Section /o "TTS only: Kokoro base assets" SEC_MODEL_PREFETCH_TTS
  SetShellVarContext current
  DetailPrint "Prefetching Kokoro TTS assets..."
  nsExec::ExecToLog '"$INSTDIR\${APP_EXE}" --prefetch-tts-assets --log-level INFO'
SectionEnd
SectionGroupEnd

Function un.KillRunningProcesses
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM BetterFingers.exe /F'
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM llama-server.exe /F'
  Sleep 600
FunctionEnd

Section "Uninstall" SEC_UNINSTALL
  SetShellVarContext current
  Call un.KillRunningProcesses

  Delete "$DESKTOP\BetterFingers.lnk"
  Delete "$SMPROGRAMS\BetterFingers\BetterFingers.lnk"
  Delete "$SMPROGRAMS\BetterFingers\Uninstall BetterFingers.lnk"
  RMDir "$SMPROGRAMS\BetterFingers"

  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "BetterFingers"
  DeleteRegKey HKCU "${UNINSTALL_REG_KEY}"
  DeleteRegKey HKCU "${APP_REG_KEY}"

  RMDir /r "$INSTDIR"
SectionEnd

Section /o "Remove user data (%APPDATA%\\BetterFingers)" SEC_UNINSTALL_USERDATA
  SetShellVarContext current
  RMDir /r "$APPDATA\BetterFingers"
  RMDir /r "$LOCALAPPDATA\BetterFingers"
SectionEnd

Function un.onInit
  SetShellVarContext current
  Call un.KillRunningProcesses

  ${GetParameters} $0
  ${GetOptions} $0 "/WIPEUSERDATA=" $1
  ${If} $1 == "1"
    SectionSetFlags ${SEC_UNINSTALL_USERDATA} ${SF_SELECTED}
  ${EndIf}
FunctionEnd
