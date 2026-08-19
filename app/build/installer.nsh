!include "nsDialogs.nsh"
!include "LogicLib.nsh"

; electron-builder compiles the uninstaller once, signs it, then compiles the
; outer installer. Do not leak uninstaller-only functions into that second
; pass or makensis correctly warns that no new uninstaller is written there.
!ifdef BUILD_UNINSTALLER

; Fixed UTF-16LE PowerShell programs used with -EncodedCommand. The only
; varying values are compile-time allowlisted relative names passed through
; private process environment variables immediately before launch.
!define BF_CANONICAL_CLEANUP_PS "JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQA9ACcAUwB0AG8AcAAnAAoAJAByAG8AbwB0AD0AWwBJAE8ALgBQAGEAdABoAF0AOgA6AEcAZQB0AEYAdQBsAGwAUABhAHQAaAAoACgASgBvAGkAbgAtAFAAYQB0AGgAIAAoAFsARQBuAHYAaQByAG8AbgBtAGUAbgB0AF0AOgA6AEcAZQB0AEYAbwBsAGQAZQByAFAAYQB0AGgAKABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdAArAFMAcABlAGMAaQBhAGwARgBvAGwAZABlAHIAXQA6ADoAQQBwAHAAbABpAGMAYQB0AGkAbwBuAEQAYQB0AGEAKQApACAAJwBCAGUAdAB0AGUAcgBGAGkAbgBnAGUAcgBzACcAKQApAAoAJAByAGUAbABhAHQAaQB2AGUAPQAkAGUAbgB2ADoAQgBGAF8AVQBOAEkATgBTAFQAQQBMAEwAXwBUAEEAUgBHAEUAVAAKACQAdABhAHIAZwBlAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARgB1AGwAbABQAGEAdABoACgAKABKAG8AaQBuAC0AUABhAHQAaAAgACQAcgBvAG8AdAAgACQAcgBlAGwAYQB0AGkAdgBlACkAKQAKAGkAZgAoAC0AbgBvAHQAIAAkAHQAYQByAGcAZQB0AC4AUwB0AGEAcgB0AHMAVwBpAHQAaAAoACQAcgBvAG8AdAAuAFQAcgBpAG0ARQBuAGQAKAAnAFwAJwApACsAJwBcACcALABbAFMAdAByAGkAbgBnAEMAbwBtAHAAYQByAGkAcwBvAG4AXQA6ADoATwByAGQAaQBuAGEAbABJAGcAbgBvAHIAZQBDAGEAcwBlACkAKQB7AGUAeABpAHQAIAAyADAAfQAKAGkAZgAoAC0AbgBvAHQAKABUAGUAcwB0AC0AUABhAHQAaAAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJAB0AGEAcgBnAGUAdAApACkAewBlAHgAaQB0ACAAMAB9AAoAZgB1AG4AYwB0AGkAbwBuACAAQQBzAHMAZQByAHQALQBOAG8AUgBlAHAAYQByAHMAZQAoAFsAcwB0AHIAaQBuAGcAXQAkAHAAYQB0AGgAKQB7ACQAaQB0AGUAbQA9AEcAZQB0AC0ASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAdABoACAALQBGAG8AcgBjAGUAOwBpAGYAKAAoACQAaQB0AGUAbQAuAEEAdAB0AHIAaQBiAHUAdABlAHMAIAAtAGIAYQBuAGQAIABbAEkATwAuAEYAaQBsAGUAQQB0AHQAcgBpAGIAdQB0AGUAcwBdADoAOgBSAGUAcABhAHIAcwBlAFAAbwBpAG4AdAApAC0AbgBlACAAMAApAHsAdABoAHIAbwB3ACAAJwByAGUAcABhAHIAcwBlACAAcABvAGkAbgB0ACAAcgBlAGYAdQBzAGUAZAAnAH0AOwBpAGYAKAAkAGkAdABlAG0ALgBQAFMASQBzAEMAbwBuAHQAYQBpAG4AZQByACkAewBmAG8AcgBlAGEAYwBoACgAJABjAGgAaQBsAGQAIABpAG4AIABHAGUAdAAtAEMAaABpAGwAZABJAHQAZQBtACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHAAYQB0AGgAIAAtAEYAbwByAGMAZQApAHsAQQBzAHMAZQByAHQALQBOAG8AUgBlAHAAYQByAHMAZQAgACQAYwBoAGkAbABkAC4ARgB1AGwAbABOAGEAbQBlAH0AfQB9AAoAaQBmACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAcgBvAG8AdAApAHsAQQBzAHMAZQByAHQALQBOAG8AUgBlAHAAYQByAHMAZQAgACQAcgBvAG8AdAB9AAoAUgBlAG0AbwB2AGUALQBJAHQAZQBtACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHQAYQByAGcAZQB0ACAALQBSAGUAYwB1AHIAcwBlACAALQBGAG8AcgBjAGUA"
!define BF_UPDATER_CLEANUP_PS "JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQA9ACcAUwB0AG8AcAAnAAoAJAByAG8AbwB0AD0AWwBJAE8ALgBQAGEAdABoAF0AOgA6AEcAZQB0AEYAdQBsAGwAUABhAHQAaAAoAFsARQBuAHYAaQByAG8AbgBtAGUAbgB0AF0AOgA6AEcAZQB0AEYAbwBsAGQAZQByAFAAYQB0AGgAKABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdAArAFMAcABlAGMAaQBhAGwARgBvAGwAZABlAHIAXQA6ADoATABvAGMAYQBsAEEAcABwAGwAaQBjAGEAdABpAG8AbgBEAGEAdABhACkAKQAKACQAdABhAHIAZwBlAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARgB1AGwAbABQAGEAdABoACgAKABKAG8AaQBuAC0AUABhAHQAaAAgACQAcgBvAG8AdAAgACQAZQBuAHYAOgBCAEYAXwBVAE4ASQBOAFMAVABBAEwATABfAEMAQQBDAEgARQApACkACgBpAGYAKAAtAG4AbwB0ACAAJAB0AGEAcgBnAGUAdAAuAFMAdABhAHIAdABzAFcAaQB0AGgAKAAkAHIAbwBvAHQALgBUAHIAaQBtAEUAbgBkACgAJwBcACcAKQArACcAXAAnACwAWwBTAHQAcgBpAG4AZwBDAG8AbQBwAGEAcgBpAHMAbwBuAF0AOgA6AE8AcgBkAGkAbgBhAGwASQBnAG4AbwByAGUAQwBhAHMAZQApACkAewBlAHgAaQB0ACAAMgAwAH0ACgBpAGYAKAAtAG4AbwB0ACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAdABhAHIAZwBlAHQAKQApAHsAZQB4AGkAdAAgADAAfQAKAGYAdQBuAGMAdABpAG8AbgAgAEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAKABbAHMAdAByAGkAbgBnAF0AJABwAGEAdABoACkAewAkAGkAdABlAG0APQBHAGUAdAAtAEkAdABlAG0AIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAcABhAHQAaAAgAC0ARgBvAHIAYwBlADsAaQBmACgAKAAkAGkAdABlAG0ALgBBAHQAdAByAGkAYgB1AHQAZQBzACAALQBiAGEAbgBkACAAWwBJAE8ALgBGAGkAbABlAEEAdAB0AHIAaQBiAHUAdABlAHMAXQA6ADoAUgBlAHAAYQByAHMAZQBQAG8AaQBuAHQAKQAtAG4AZQAgADAAKQB7AHQAaAByAG8AdwAgACcAcgBlAHAAYQByAHMAZQAgAHAAbwBpAG4AdAAgAHIAZQBmAHUAcwBlAGQAJwB9ADsAaQBmACgAJABpAHQAZQBtAC4AUABTAEkAcwBDAG8AbgB0AGEAaQBuAGUAcgApAHsAZgBvAHIAZQBhAGMAaAAoACQAYwBoAGkAbABkACAAaQBuACAARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAdABoACAALQBGAG8AcgBjAGUAKQB7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAGMAaABpAGwAZAAuAEYAdQBsAGwATgBhAG0AZQB9AH0AfQAKAEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAHQAYQByAGcAZQB0AAoAUgBlAG0AbwB2AGUALQBJAHQAZQBtACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHQAYQByAGcAZQB0ACAALQBSAGUAYwB1AHIAcwBlACAALQBGAG8AcgBjAGUA"

Var BfCleanupDialog
Var BfModelsCheckbox
Var BfRecordingsCheckbox
Var BfHistoryCheckbox
Var BfSettingsCheckbox
Var BfLogsCheckbox
Var BfDeleteModels
Var BfDeleteRecordings
Var BfDeleteHistory
Var BfDeleteSettings
Var BfDeleteLogs

!macro customUnInit
  ; Exact automation flags let the signed installer smoke test exercise each
  ; explicit category without GUI automation. They are never implied by /S.
  ${GetParameters} $R0
  ${GetOptions} $R0 "/BF_DELETE_MODELS" $R1
  ${IfNot} ${Errors}
    StrCpy $BfDeleteModels ${BST_CHECKED}
  ${EndIf}
  ${GetOptions} $R0 "/BF_DELETE_RECORDINGS" $R1
  ${IfNot} ${Errors}
    StrCpy $BfDeleteRecordings ${BST_CHECKED}
  ${EndIf}
  ${GetOptions} $R0 "/BF_DELETE_HISTORY" $R1
  ${IfNot} ${Errors}
    StrCpy $BfDeleteHistory ${BST_CHECKED}
  ${EndIf}
  ${GetOptions} $R0 "/BF_DELETE_SETTINGS" $R1
  ${IfNot} ${Errors}
    StrCpy $BfDeleteSettings ${BST_CHECKED}
  ${EndIf}
  ${GetOptions} $R0 "/BF_DELETE_LOGS" $R1
  ${IfNot} ${Errors}
    StrCpy $BfDeleteLogs ${BST_CHECKED}
  ${EndIf}
!macroend

; Replace only the stock uninstall welcome-page declaration so the cleanup
; choices appear before MUI_UNPAGE_INSTFILES. Every choice remains unchecked.
!macro customUnWelcomePage
  !insertmacro MUI_UNPAGE_WELCOME
  UninstPage custom un.BfCleanupCreate un.BfCleanupLeave
!macroend

Function un.BfCleanupCreate
  nsDialogs::Create 1018
  Pop $BfCleanupDialog
  ${If} $BfCleanupDialog == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 26u "Optional BetterFingers data cleanup"
  Pop $0
  CreateFont $1 "$(^Font)" "10" "700"
  SendMessage $0 ${WM_SETFONT} $1 1

  ${NSD_CreateLabel} 0 27u 100% 26u "Program files are removed automatically. Your data stays unless you select a category below."
  Pop $0
  ${NSD_CreateLabel} 0 55u 100% 22u "Canonical data folder: $APPDATA\BetterFingers"
  Pop $0

  ${NSD_CreateCheckbox} 0 82u 100% 18u "Downloaded models and runtimes"
  Pop $BfModelsCheckbox
  ${NSD_Uncheck} $BfModelsCheckbox
  ${NSD_CreateCheckbox} 0 104u 100% 18u "Recordings and custom voices"
  Pop $BfRecordingsCheckbox
  ${NSD_Uncheck} $BfRecordingsCheckbox
  ${NSD_CreateCheckbox} 0 126u 100% 18u "History, drafts, and exports"
  Pop $BfHistoryCheckbox
  ${NSD_Uncheck} $BfHistoryCheckbox
  ${NSD_CreateCheckbox} 0 148u 100% 28u "Settings, profiles, personas, dictionary, contacts, and workflows"
  Pop $BfSettingsCheckbox
  ${NSD_Uncheck} $BfSettingsCheckbox
  ${NSD_CreateCheckbox} 0 178u 100% 18u "Logs and temporary data"
  Pop $BfLogsCheckbox
  ${NSD_Uncheck} $BfLogsCheckbox

  ${NSD_CreateLabel} 0 205u 100% 28u "Custom BETTERFINGERS_DATA_DIR and model-path overrides are never followed here. Use Factory Reset inside BetterFingers for advanced cleanup."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function un.BfCleanupLeave
  ${NSD_GetState} $BfModelsCheckbox $BfDeleteModels
  ${NSD_GetState} $BfRecordingsCheckbox $BfDeleteRecordings
  ${NSD_GetState} $BfHistoryCheckbox $BfDeleteHistory
  ${NSD_GetState} $BfSettingsCheckbox $BfDeleteSettings
  ${NSD_GetState} $BfLogsCheckbox $BfDeleteLogs

  StrCpy $0 ""
  ${If} $BfDeleteModels == ${BST_CHECKED}
    StrCpy $0 "$0$\r$\n• Downloaded models and runtimes"
  ${EndIf}
  ${If} $BfDeleteRecordings == ${BST_CHECKED}
    StrCpy $0 "$0$\r$\n• Recordings and custom voices"
  ${EndIf}
  ${If} $BfDeleteHistory == ${BST_CHECKED}
    StrCpy $0 "$0$\r$\n• History, drafts, and exports"
  ${EndIf}
  ${If} $BfDeleteSettings == ${BST_CHECKED}
    StrCpy $0 "$0$\r$\n• Settings, profiles, personas, dictionary, contacts, and workflows"
  ${EndIf}
  ${If} $BfDeleteLogs == ${BST_CHECKED}
    StrCpy $0 "$0$\r$\n• Logs and temporary data"
  ${EndIf}
  ${If} $0 != ""
    MessageBox MB_ICONEXCLAMATION|MB_YESNO|MB_DEFBUTTON2 \
      "Permanently delete these selected categories from:$\r$\n$APPDATA\BetterFingers$0$\r$\n$\r$\nThis cannot be undone." \
      IDYES +2
    Abort
  ${EndIf}
FunctionEnd

; PowerShell receives only compile-time literal relative names. It recomputes
; the canonical root itself, proves the target stays below it, recursively
; rejects reparse points before deletion, and never reads environment override
; files. A nonzero result fails closed and leaves the target untouched.
!macro BfSafeDeleteCanonical RelativePath
  DetailPrint "Checking canonical BetterFingers data path: ${RelativePath}"
  System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_TARGET", "${RelativePath}").r2'
  ${If} $2 == 0
    DetailPrint "Refused to prepare canonical cleanup for ${RelativePath}."
  ${Else}
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -EncodedCommand ${BF_CANONICAL_CLEANUP_PS}'
    Pop $0
    Pop $1
    System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_TARGET", "").r2'
    ${If} $0 != 0
      DetailPrint "Refused to delete ${RelativePath}; canonical/reparse safety check failed (exit $0)."
    ${EndIf}
  ${EndIf}
!macroend

!macro BfSafeDeleteUpdaterCache CacheName
  DetailPrint "Removing completed updater staging: ${CacheName}"
  System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_CACHE", "${CacheName}").r2'
  ${If} $2 == 0
    DetailPrint "Refused to prepare updater staging cleanup for ${CacheName}."
  ${Else}
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -EncodedCommand ${BF_UPDATER_CLEANUP_PS}'
    Pop $0
    Pop $1
    System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_CACHE", "").r2'
    ${If} $0 != 0
      DetailPrint "Refused to delete updater staging ${CacheName} (exit $0)."
    ${EndIf}
  ${EndIf}
!macroend

!macro customUnInstall
  ; electron-builder also runs the old uninstaller during an upgrade. Never
  ; touch user data or the active updater cache on that path.
  ${IfNot} ${isUpdated}
    !insertmacro BfSafeDeleteUpdaterCache "betterfingers-electron-updater"
    !insertmacro BfSafeDeleteUpdaterCache "BetterFingers-updater"

    ${If} $BfDeleteModels == ${BST_CHECKED}
      !insertmacro BfSafeDeleteCanonical "models"
      !insertmacro BfSafeDeleteCanonical "wake_models"
    ${EndIf}
    ${If} $BfDeleteRecordings == ${BST_CHECKED}
      !insertmacro BfSafeDeleteCanonical "recordings"
      !insertmacro BfSafeDeleteCanonical "voices"
    ${EndIf}
    ${If} $BfDeleteHistory == ${BST_CHECKED}
      !insertmacro BfSafeDeleteCanonical "draft_history.json"
      !insertmacro BfSafeDeleteCanonical "history.db"
      !insertmacro BfSafeDeleteCanonical "history.db-wal"
      !insertmacro BfSafeDeleteCanonical "history.db-shm"
      !insertmacro BfSafeDeleteCanonical "history.db-journal"
      !insertmacro BfSafeDeleteCanonical "drafts"
      !insertmacro BfSafeDeleteCanonical "exports"
    ${EndIf}
    ${If} $BfDeleteSettings == ${BST_CHECKED}
      !insertmacro BfSafeDeleteCanonical "profiles"
      !insertmacro BfSafeDeleteCanonical "config.yaml"
      !insertmacro BfSafeDeleteCanonical "personas.yaml"
      !insertmacro BfSafeDeleteCanonical "dictionary.json"
      !insertmacro BfSafeDeleteCanonical "macros.json"
      !insertmacro BfSafeDeleteCanonical "contacts.json"
      !insertmacro BfSafeDeleteCanonical "persona_learning.json"
      !insertmacro BfSafeDeleteCanonical "user_profile.json"
      !insertmacro BfSafeDeleteCanonical "mcp_servers.json"
      !insertmacro BfSafeDeleteCanonical "graph.json"
      !insertmacro BfSafeDeleteCanonical "app_profiles.json"
      !insertmacro BfSafeDeleteCanonical "launcher_workflows.json"
      !insertmacro BfSafeDeleteCanonical "application_registry.json"
      !insertmacro BfSafeDeleteCanonical "controller_bindings.json"
      !insertmacro BfSafeDeleteCanonical "stream_deck_config.json"
      !insertmacro BfSafeDeleteCanonical "voice_presets.json"
      !insertmacro BfSafeDeleteCanonical "app_state.yaml"
      !insertmacro BfSafeDeleteCanonical ".first_run_complete"
      !insertmacro BfSafeDeleteCanonical "onboarding.json"
      !insertmacro BfSafeDeleteCanonical "overlay-position.json"
      !insertmacro BfSafeDeleteCanonical "overlay-appearance.json"
    ${EndIf}
    ${If} $BfDeleteLogs == ${BST_CHECKED}
      !insertmacro BfSafeDeleteCanonical "tmp"
      !insertmacro BfSafeDeleteCanonical "cache"
      !insertmacro BfSafeDeleteCanonical "logs"
      !insertmacro BfSafeDeleteCanonical "debug.log"
      !insertmacro BfSafeDeleteCanonical "sidecar_backend_raw.log"
    ${EndIf}

    ; Remove the canonical root only if every remaining entry was selected and
    ; safely removed. Unknown files keep the directory alive by design.
    RMDir "$APPDATA\BetterFingers"
  ${EndIf}
!macroend

!endif
