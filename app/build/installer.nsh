!include "nsDialogs.nsh"
!include "LogicLib.nsh"

; electron-builder compiles the uninstaller once, signs it, then compiles the
; outer installer. Do not leak uninstaller-only functions into that second
; pass or makensis correctly warns that no new uninstaller is written there.
!ifdef BUILD_UNINSTALLER

; Fixed UTF-16LE PowerShell programs used with -EncodedCommand. The only
; varying values are compile-time allowlisted relative names passed through
; private process environment variables immediately before launch.
!define BF_CANONICAL_CLEANUP_PS "JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQA9ACcAUwB0AG8AcAAnAAoAJAByAG8AbwB0AD0AWwBJAE8ALgBQAGEAdABoAF0AOgA6AEcAZQB0AEYAdQBsAGwAUABhAHQAaAAoACgASgBvAGkAbgAtAFAAYQB0AGgAIAAoAFsARQBuAHYAaQByAG8AbgBtAGUAbgB0AF0AOgA6AEcAZQB0AEYAbwBsAGQAZQByAFAAYQB0AGgAKABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdAArAFMAcABlAGMAaQBhAGwARgBvAGwAZABlAHIAXQA6ADoAQQBwAHAAbABpAGMAYQB0AGkAbwBuAEQAYQB0AGEAKQApACAAJwBCAGUAdAB0AGUAcgBGAGkAbgBnAGUAcgBzACcAKQApAAoAJAByAGUAbABhAHQAaQB2AGUAPQAkAGUAbgB2ADoAQgBGAF8AVQBOAEkATgBTAFQAQQBMAEwAXwBUAEEAUgBHAEUAVAAKACQAdABhAHIAZwBlAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARgB1AGwAbABQAGEAdABoACgAKABKAG8AaQBuAC0AUABhAHQAaAAgACQAcgBvAG8AdAAgACQAcgBlAGwAYQB0AGkAdgBlACkAKQAKAGkAZgAoAC0AbgBvAHQAIAAkAHQAYQByAGcAZQB0AC4AUwB0AGEAcgB0AHMAVwBpAHQAaAAoACQAcgBvAG8AdAAuAFQAcgBpAG0ARQBuAGQAKAAnAFwAJwApACsAJwBcACcALABbAFMAdAByAGkAbgBnAEMAbwBtAHAAYQByAGkAcwBvAG4AXQA6ADoATwByAGQAaQBuAGEAbABJAGcAbgBvAHIAZQBDAGEAcwBlACkAKQB7AGUAeABpAHQAIAAyADAAfQAKAGkAZgAoACQAdABhAHIAZwBlAHQALgBUAHIAaQBtAEUAbgBkACgAJwBcACcAKQAgAC0AZQBxACAAJAByAG8AbwB0AC4AVAByAGkAbQBFAG4AZAAoACcAXAAnACkAKQB7AGUAeABpAHQAIAAyADAAfQAKAGYAdQBuAGMAdABpAG8AbgAgAEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAKABbAHMAdAByAGkAbgBnAF0AJABwAGEAdABoACkAewAkAGkAdABlAG0APQBHAGUAdAAtAEkAdABlAG0AIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAcABhAHQAaAAgAC0ARgBvAHIAYwBlADsAaQBmACgAKAAkAGkAdABlAG0ALgBBAHQAdAByAGkAYgB1AHQAZQBzACAALQBiAGEAbgBkACAAWwBJAE8ALgBGAGkAbABlAEEAdAB0AHIAaQBiAHUAdABlAHMAXQA6ADoAUgBlAHAAYQByAHMAZQBQAG8AaQBuAHQAKQAtAG4AZQAgADAAKQB7AHQAaAByAG8AdwAgACcAcgBlAHAAYQByAHMAZQAgAHAAbwBpAG4AdAAgAHIAZQBmAHUAcwBlAGQAJwB9ADsAaQBmACgAJABpAHQAZQBtAC4AUABTAEkAcwBDAG8AbgB0AGEAaQBuAGUAcgApAHsAZgBvAHIAZQBhAGMAaAAoACQAYwBoAGkAbABkACAAaQBuACAARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAdABoACAALQBGAG8AcgBjAGUAKQB7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAGMAaABpAGwAZAAuAEYAdQBsAGwATgBhAG0AZQB9AH0AfQAKACQAcwBoAGEAcABlAHMAPQAnAGIAYQBrAC0AdgBbADAALQA5AF0AKwB8AGMAbwByAHIAdQBwAHQAfABbADAALQA5AF0AKwBcAC4AYwBvAHIAcgB1AHAAdAB8AGMAbwByAHIAdQBwAHQALQAuACsAfABtAGkAZwByAGEAdABlAGQAJwAKACQAcwBpAGIAbABpAG4AZwBzAD0AQAAoACkACgBpAGYAKAAtAG4AbwB0ACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAdABhAHIAZwBlAHQAIAAtAFAAYQB0AGgAVAB5AHAAZQAgAEMAbwBuAHQAYQBpAG4AZQByACkAKQB7ACQAcABhAHIAZQBuAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARABpAHIAZQBjAHQAbwByAHkATgBhAG0AZQAoACQAdABhAHIAZwBlAHQAKQA7AGkAZgAoAFQAZQBzAHQALQBQAGEAdABoACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHAAYQByAGUAbgB0ACAALQBQAGEAdABoAFQAeQBwAGUAIABDAG8AbgB0AGEAaQBuAGUAcgApAHsAJABwAGEAdAB0AGUAcgBuAD0AJwBeACcAKwBbAHIAZQBnAGUAeABdADoAOgBFAHMAYwBhAHAAZQAoAFsASQBPAC4AUABhAHQAaABdADoAOgBHAGUAdABGAGkAbABlAE4AYQBtAGUAKAAkAHQAYQByAGcAZQB0ACkAKQArACcAXAAuACgAJwArACQAcwBoAGEAcABlAHMAKwAnACkAJAAnADsAZgBvAHIAZQBhAGMAaAAoACQAZQBuAHQAcgB5ACAAaQBuACAARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAcgBlAG4AdAAgAC0ARgBvAHIAYwBlACkAewBpAGYAKAAkAGUAbgB0AHIAeQAuAE4AYQBtAGUAIAAtAG0AYQB0AGMAaAAgACQAcABhAHQAdABlAHIAbgApAHsAaQBmACgALQBuAG8AdAAgACQAZQBuAHQAcgB5AC4ARgB1AGwAbABOAGEAbQBlAC4AUwB0AGEAcgB0AHMAVwBpAHQAaAAoACQAcgBvAG8AdAAuAFQAcgBpAG0ARQBuAGQAKAAnAFwAJwApACsAJwBcACcALABbAFMAdAByAGkAbgBnAEMAbwBtAHAAYQByAGkAcwBvAG4AXQA6ADoATwByAGQAaQBuAGEAbABJAGcAbgBvAHIAZQBDAGEAcwBlACkAKQB7AGUAeABpAHQAIAAyADAAfQA7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAGUAbgB0AHIAeQAuAEYAdQBsAGwATgBhAG0AZQA7AGkAZgAoAC0AbgBvAHQAIAAkAGUAbgB0AHIAeQAuAFAAUwBJAHMAQwBvAG4AdABhAGkAbgBlAHIAKQB7ACQAcwBpAGIAbABpAG4AZwBzACsAPQAkAGUAbgB0AHIAeQAuAEYAdQBsAGwATgBhAG0AZQB9AH0AfQB9AH0ACgBpAGYAKAAtAG4AbwB0ACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAdABhAHIAZwBlAHQAKQAgAC0AYQBuAGQAIAAkAHMAaQBiAGwAaQBuAGcAcwAuAEMAbwB1AG4AdAAgAC0AZQBxACAAMAApAHsAZQB4AGkAdAAgADAAfQAKAGkAZgAoAFQAZQBzAHQALQBQAGEAdABoACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHIAbwBvAHQAKQB7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAHIAbwBvAHQAfQAKACQAZgBhAGkAbABlAGQAPQAwAAoAZgBvAHIAZQBhAGMAaAAoACQAcwBpAGIAbABpAG4AZwAgAGkAbgAgACQAcwBpAGIAbABpAG4AZwBzACkAewB0AHIAeQB7AFIAZQBtAG8AdgBlAC0ASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABzAGkAYgBsAGkAbgBnACAALQBGAG8AcgBjAGUAfQBjAGEAdABjAGgAewAkAGYAYQBpAGwAZQBkAD0AMQB9AH0ACgBpAGYAKABUAGUAcwB0AC0AUABhAHQAaAAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJAB0AGEAcgBnAGUAdAApAHsAUgBlAG0AbwB2AGUALQBJAHQAZQBtACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHQAYQByAGcAZQB0ACAALQBSAGUAYwB1AHIAcwBlACAALQBGAG8AcgBjAGUAfQAKAGUAeABpAHQAIAAkAGYAYQBpAGwAZQBkAA=="
!define BF_UPDATER_CLEANUP_PS "JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQA9ACcAUwB0AG8AcAAnAAoAJAByAG8AbwB0AD0AWwBJAE8ALgBQAGEAdABoAF0AOgA6AEcAZQB0AEYAdQBsAGwAUABhAHQAaAAoAFsARQBuAHYAaQByAG8AbgBtAGUAbgB0AF0AOgA6AEcAZQB0AEYAbwBsAGQAZQByAFAAYQB0AGgAKABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdAArAFMAcABlAGMAaQBhAGwARgBvAGwAZABlAHIAXQA6ADoATABvAGMAYQBsAEEAcABwAGwAaQBjAGEAdABpAG8AbgBEAGEAdABhACkAKQAKACQAdABhAHIAZwBlAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARgB1AGwAbABQAGEAdABoACgAKABKAG8AaQBuAC0AUABhAHQAaAAgACQAcgBvAG8AdAAgACQAZQBuAHYAOgBCAEYAXwBVAE4ASQBOAFMAVABBAEwATABfAEMAQQBDAEgARQApACkACgBpAGYAKAAtAG4AbwB0ACAAJAB0AGEAcgBnAGUAdAAuAFMAdABhAHIAdABzAFcAaQB0AGgAKAAkAHIAbwBvAHQALgBUAHIAaQBtAEUAbgBkACgAJwBcACcAKQArACcAXAAnACwAWwBTAHQAcgBpAG4AZwBDAG8AbQBwAGEAcgBpAHMAbwBuAF0AOgA6AE8AcgBkAGkAbgBhAGwASQBnAG4AbwByAGUAQwBhAHMAZQApACkAewBlAHgAaQB0ACAAMgAwAH0ACgBpAGYAKAAtAG4AbwB0ACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAdABhAHIAZwBlAHQAKQApAHsAZQB4AGkAdAAgADAAfQAKAGYAdQBuAGMAdABpAG8AbgAgAEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAKABbAHMAdAByAGkAbgBnAF0AJABwAGEAdABoACkAewAkAGkAdABlAG0APQBHAGUAdAAtAEkAdABlAG0AIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAcABhAHQAaAAgAC0ARgBvAHIAYwBlADsAaQBmACgAKAAkAGkAdABlAG0ALgBBAHQAdAByAGkAYgB1AHQAZQBzACAALQBiAGEAbgBkACAAWwBJAE8ALgBGAGkAbABlAEEAdAB0AHIAaQBiAHUAdABlAHMAXQA6ADoAUgBlAHAAYQByAHMAZQBQAG8AaQBuAHQAKQAtAG4AZQAgADAAKQB7AHQAaAByAG8AdwAgACcAcgBlAHAAYQByAHMAZQAgAHAAbwBpAG4AdAAgAHIAZQBmAHUAcwBlAGQAJwB9ADsAaQBmACgAJABpAHQAZQBtAC4AUABTAEkAcwBDAG8AbgB0AGEAaQBuAGUAcgApAHsAZgBvAHIAZQBhAGMAaAAoACQAYwBoAGkAbABkACAAaQBuACAARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAdABoACAALQBGAG8AcgBjAGUAKQB7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAGMAaABpAGwAZAAuAEYAdQBsAGwATgBhAG0AZQB9AH0AfQAKAEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAHQAYQByAGcAZQB0AAoAUgBlAG0AbwB2AGUALQBJAHQAZQBtACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHQAYQByAGcAZQB0ACAALQBSAGUAYwB1AHIAcwBlACAALQBGAG8AcgBjAGUA"

; The packaged app's Electron userData is %APPDATA%\betterfingers-electron, NOT the canonical
; %APPDATA%\BetterFingers (measured on the unpacked alpha.4 build: electron-builder's productName
; never reaches app.asar/package.json, so Electron names the folder after the package "name").
; Chromium's renderer state (Local Storage, which holds the legacy consent flag, and the caches)
; and the overlay/sidecar-log files live there, out of reach of BF_CANONICAL_CLEANUP_PS. This is
; that SAME program with exactly one literal changed, 'BetterFingers' -> 'betterfingers-electron'
; (a contract test re-derives it and fails on any other difference), so it has the same root
; confinement, reparse-point refusal and exact-name sibling handling.
!define BF_ELECTRON_CLEANUP_PS "JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQA9ACcAUwB0AG8AcAAnAAoAJAByAG8AbwB0AD0AWwBJAE8ALgBQAGEAdABoAF0AOgA6AEcAZQB0AEYAdQBsAGwAUABhAHQAaAAoACgASgBvAGkAbgAtAFAAYQB0AGgAIAAoAFsARQBuAHYAaQByAG8AbgBtAGUAbgB0AF0AOgA6AEcAZQB0AEYAbwBsAGQAZQByAFAAYQB0AGgAKABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdAArAFMAcABlAGMAaQBhAGwARgBvAGwAZABlAHIAXQA6ADoAQQBwAHAAbABpAGMAYQB0AGkAbwBuAEQAYQB0AGEAKQApACAAJwBiAGUAdAB0AGUAcgBmAGkAbgBnAGUAcgBzAC0AZQBsAGUAYwB0AHIAbwBuACcAKQApAAoAJAByAGUAbABhAHQAaQB2AGUAPQAkAGUAbgB2ADoAQgBGAF8AVQBOAEkATgBTAFQAQQBMAEwAXwBUAEEAUgBHAEUAVAAKACQAdABhAHIAZwBlAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARgB1AGwAbABQAGEAdABoACgAKABKAG8AaQBuAC0AUABhAHQAaAAgACQAcgBvAG8AdAAgACQAcgBlAGwAYQB0AGkAdgBlACkAKQAKAGkAZgAoAC0AbgBvAHQAIAAkAHQAYQByAGcAZQB0AC4AUwB0AGEAcgB0AHMAVwBpAHQAaAAoACQAcgBvAG8AdAAuAFQAcgBpAG0ARQBuAGQAKAAnAFwAJwApACsAJwBcACcALABbAFMAdAByAGkAbgBnAEMAbwBtAHAAYQByAGkAcwBvAG4AXQA6ADoATwByAGQAaQBuAGEAbABJAGcAbgBvAHIAZQBDAGEAcwBlACkAKQB7AGUAeABpAHQAIAAyADAAfQAKAGkAZgAoACQAdABhAHIAZwBlAHQALgBUAHIAaQBtAEUAbgBkACgAJwBcACcAKQAgAC0AZQBxACAAJAByAG8AbwB0AC4AVAByAGkAbQBFAG4AZAAoACcAXAAnACkAKQB7AGUAeABpAHQAIAAyADAAfQAKAGYAdQBuAGMAdABpAG8AbgAgAEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAKABbAHMAdAByAGkAbgBnAF0AJABwAGEAdABoACkAewAkAGkAdABlAG0APQBHAGUAdAAtAEkAdABlAG0AIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAcABhAHQAaAAgAC0ARgBvAHIAYwBlADsAaQBmACgAKAAkAGkAdABlAG0ALgBBAHQAdAByAGkAYgB1AHQAZQBzACAALQBiAGEAbgBkACAAWwBJAE8ALgBGAGkAbABlAEEAdAB0AHIAaQBiAHUAdABlAHMAXQA6ADoAUgBlAHAAYQByAHMAZQBQAG8AaQBuAHQAKQAtAG4AZQAgADAAKQB7AHQAaAByAG8AdwAgACcAcgBlAHAAYQByAHMAZQAgAHAAbwBpAG4AdAAgAHIAZQBmAHUAcwBlAGQAJwB9ADsAaQBmACgAJABpAHQAZQBtAC4AUABTAEkAcwBDAG8AbgB0AGEAaQBuAGUAcgApAHsAZgBvAHIAZQBhAGMAaAAoACQAYwBoAGkAbABkACAAaQBuACAARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAdABoACAALQBGAG8AcgBjAGUAKQB7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAGMAaABpAGwAZAAuAEYAdQBsAGwATgBhAG0AZQB9AH0AfQAKACQAcwBoAGEAcABlAHMAPQAnAGIAYQBrAC0AdgBbADAALQA5AF0AKwB8AGMAbwByAHIAdQBwAHQAfABbADAALQA5AF0AKwBcAC4AYwBvAHIAcgB1AHAAdAB8AGMAbwByAHIAdQBwAHQALQAuACsAfABtAGkAZwByAGEAdABlAGQAJwAKACQAcwBpAGIAbABpAG4AZwBzAD0AQAAoACkACgBpAGYAKAAtAG4AbwB0ACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAdABhAHIAZwBlAHQAIAAtAFAAYQB0AGgAVAB5AHAAZQAgAEMAbwBuAHQAYQBpAG4AZQByACkAKQB7ACQAcABhAHIAZQBuAHQAPQBbAEkATwAuAFAAYQB0AGgAXQA6ADoARwBlAHQARABpAHIAZQBjAHQAbwByAHkATgBhAG0AZQAoACQAdABhAHIAZwBlAHQAKQA7AGkAZgAoAFQAZQBzAHQALQBQAGEAdABoACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHAAYQByAGUAbgB0ACAALQBQAGEAdABoAFQAeQBwAGUAIABDAG8AbgB0AGEAaQBuAGUAcgApAHsAJABwAGEAdAB0AGUAcgBuAD0AJwBeACcAKwBbAHIAZQBnAGUAeABdADoAOgBFAHMAYwBhAHAAZQAoAFsASQBPAC4AUABhAHQAaABdADoAOgBHAGUAdABGAGkAbABlAE4AYQBtAGUAKAAkAHQAYQByAGcAZQB0ACkAKQArACcAXAAuACgAJwArACQAcwBoAGEAcABlAHMAKwAnACkAJAAnADsAZgBvAHIAZQBhAGMAaAAoACQAZQBuAHQAcgB5ACAAaQBuACAARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABwAGEAcgBlAG4AdAAgAC0ARgBvAHIAYwBlACkAewBpAGYAKAAkAGUAbgB0AHIAeQAuAE4AYQBtAGUAIAAtAG0AYQB0AGMAaAAgACQAcABhAHQAdABlAHIAbgApAHsAaQBmACgALQBuAG8AdAAgACQAZQBuAHQAcgB5AC4ARgB1AGwAbABOAGEAbQBlAC4AUwB0AGEAcgB0AHMAVwBpAHQAaAAoACQAcgBvAG8AdAAuAFQAcgBpAG0ARQBuAGQAKAAnAFwAJwApACsAJwBcACcALABbAFMAdAByAGkAbgBnAEMAbwBtAHAAYQByAGkAcwBvAG4AXQA6ADoATwByAGQAaQBuAGEAbABJAGcAbgBvAHIAZQBDAGEAcwBlACkAKQB7AGUAeABpAHQAIAAyADAAfQA7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAGUAbgB0AHIAeQAuAEYAdQBsAGwATgBhAG0AZQA7AGkAZgAoAC0AbgBvAHQAIAAkAGUAbgB0AHIAeQAuAFAAUwBJAHMAQwBvAG4AdABhAGkAbgBlAHIAKQB7ACQAcwBpAGIAbABpAG4AZwBzACsAPQAkAGUAbgB0AHIAeQAuAEYAdQBsAGwATgBhAG0AZQB9AH0AfQB9AH0ACgBpAGYAKAAtAG4AbwB0ACgAVABlAHMAdAAtAFAAYQB0AGgAIAAtAEwAaQB0AGUAcgBhAGwAUABhAHQAaAAgACQAdABhAHIAZwBlAHQAKQAgAC0AYQBuAGQAIAAkAHMAaQBiAGwAaQBuAGcAcwAuAEMAbwB1AG4AdAAgAC0AZQBxACAAMAApAHsAZQB4AGkAdAAgADAAfQAKAGkAZgAoAFQAZQBzAHQALQBQAGEAdABoACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHIAbwBvAHQAKQB7AEEAcwBzAGUAcgB0AC0ATgBvAFIAZQBwAGEAcgBzAGUAIAAkAHIAbwBvAHQAfQAKACQAZgBhAGkAbABlAGQAPQAwAAoAZgBvAHIAZQBhAGMAaAAoACQAcwBpAGIAbABpAG4AZwAgAGkAbgAgACQAcwBpAGIAbABpAG4AZwBzACkAewB0AHIAeQB7AFIAZQBtAG8AdgBlAC0ASQB0AGUAbQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJABzAGkAYgBsAGkAbgBnACAALQBGAG8AcgBjAGUAfQBjAGEAdABjAGgAewAkAGYAYQBpAGwAZQBkAD0AMQB9AH0ACgBpAGYAKABUAGUAcwB0AC0AUABhAHQAaAAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJAB0AGEAcgBnAGUAdAApAHsAUgBlAG0AbwB2AGUALQBJAHQAZQBtACAALQBMAGkAdABlAHIAYQBsAFAAYQB0AGgAIAAkAHQAYQByAGcAZQB0ACAALQBSAGUAYwB1AHIAcwBlACAALQBGAG8AcgBjAGUAfQAKAGUAeABpAHQAIAAkAGYAYQBpAGwAZQBkAA=="

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
  ${NSD_CreateLabel} 0 55u 100% 22u "Canonical data folder: $APPDATA\BetterFingers (and $APPDATA\betterfingers-electron)"
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
      "Permanently delete these selected categories from:$\r$\n$APPDATA\BetterFingers and $APPDATA\betterfingers-electron$0$\r$\n$\r$\nThis cannot be undone." \
      IDYES +2
    Abort
  ${EndIf}
FunctionEnd

; PowerShell receives only compile-time literal relative names. It recomputes
; the canonical root itself, proves the target stays below it, recursively
; rejects reparse points before deletion, and never reads environment override
; files. A nonzero result fails closed and leaves the target untouched.
; For a target that is not an existing directory it also deletes that store's
; recovery siblings -- <name>.bak-v<N>, <name>.corrupt, <name>.<ts>.corrupt,
; <name>.corrupt-<tag> and <name>.migrated -- matched by exact name in the same
; folder (backend/privacy/data_paths.py declares these shapes; the installer
; contract tests keep the two in step). Every sibling passes the same root and
; reparse-point checks before anything at all is deleted.
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

; Same as BfSafeDeleteCanonical but rooted at %APPDATA%\betterfingers-electron (Electron's own
; userData folder). Only literal, allowlisted relative names are ever passed.
!macro BfSafeDeleteElectron RelativePath
  DetailPrint "Checking Electron user-data path: ${RelativePath}"
  System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_TARGET", "${RelativePath}").r2'
  ${If} $2 == 0
    DetailPrint "Refused to prepare Electron cleanup for ${RelativePath}."
  ${Else}
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -EncodedCommand ${BF_ELECTRON_CLEANUP_PS}'
    Pop $0
    Pop $1
    System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_TARGET", "").r2'
    ${If} $0 != 0
      DetailPrint "Refused to delete ${RelativePath}; Electron user-data safety check failed (exit $0)."
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
      !insertmacro BfSafeDeleteCanonical "tts"
      !insertmacro BfSafeDeleteCanonical "runtimes"
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
      !insertmacro BfSafeDeleteCanonical "persona_drafts.json"
      !insertmacro BfSafeDeleteCanonical "dictionary.json"
      !insertmacro BfSafeDeleteCanonical "macros.json"
      !insertmacro BfSafeDeleteCanonical "contacts.json"
      !insertmacro BfSafeDeleteCanonical "persona_learning.json"
      !insertmacro BfSafeDeleteCanonical "user_profile.json"
      !insertmacro BfSafeDeleteCanonical "mcp_servers.json"
      !insertmacro BfSafeDeleteCanonical "mcp_trust.json"
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
      ; The same two files, where the packaged app really writes them.
      !insertmacro BfSafeDeleteElectron "overlay-position.json"
      !insertmacro BfSafeDeleteElectron "overlay-appearance.json"
      ; Renderer state: the first-run flags and the LEGACY consent flag live in Local Storage, so
      ; it goes with onboarding.json, or a reinstall would migrate the old flag and skip consent.
      !insertmacro BfSafeDeleteElectron "Local Storage"
      !insertmacro BfSafeDeleteCanonical "Local Storage"
      !insertmacro BfSafeDeleteElectron "Session Storage"
      !insertmacro BfSafeDeleteCanonical "Session Storage"
      !insertmacro BfSafeDeleteElectron "IndexedDB"
      !insertmacro BfSafeDeleteCanonical "IndexedDB"
      !insertmacro BfSafeDeleteElectron "WebStorage"
      !insertmacro BfSafeDeleteCanonical "WebStorage"
      !insertmacro BfSafeDeleteElectron "SharedStorage"
      !insertmacro BfSafeDeleteCanonical "SharedStorage"
      !insertmacro BfSafeDeleteElectron "SharedStorage-wal"
      !insertmacro BfSafeDeleteCanonical "SharedStorage-wal"
      !insertmacro BfSafeDeleteElectron "SharedStorage-shm"
      !insertmacro BfSafeDeleteCanonical "SharedStorage-shm"
      !insertmacro BfSafeDeleteElectron "SharedStorage-journal"
      !insertmacro BfSafeDeleteCanonical "SharedStorage-journal"
      !insertmacro BfSafeDeleteElectron "Service Worker"
      !insertmacro BfSafeDeleteCanonical "Service Worker"
      !insertmacro BfSafeDeleteElectron "File System"
      !insertmacro BfSafeDeleteCanonical "File System"
      !insertmacro BfSafeDeleteElectron "databases"
      !insertmacro BfSafeDeleteCanonical "databases"
      !insertmacro BfSafeDeleteElectron "blob_storage"
      !insertmacro BfSafeDeleteCanonical "blob_storage"
    ${EndIf}
    ${If} $BfDeleteLogs == ${BST_CHECKED}
      !insertmacro BfSafeDeleteCanonical "tmp"
      !insertmacro BfSafeDeleteCanonical "cache"
      !insertmacro BfSafeDeleteCanonical "logs"
      !insertmacro BfSafeDeleteCanonical "debug.log"
      !insertmacro BfSafeDeleteCanonical "audio_privacy_journal.json"
      !insertmacro BfSafeDeleteCanonical "sidecar_backend_raw.log"
      !insertmacro BfSafeDeleteElectron "sidecar_backend_raw.log"
      ; Chromium's caches and engine bookkeeping (and the factory-reset marker).
      !insertmacro BfSafeDeleteElectron "Network"
      !insertmacro BfSafeDeleteCanonical "Network"
      !insertmacro BfSafeDeleteElectron "Cache"
      !insertmacro BfSafeDeleteElectron "Code Cache"
      !insertmacro BfSafeDeleteCanonical "Code Cache"
      !insertmacro BfSafeDeleteElectron "GPUCache"
      !insertmacro BfSafeDeleteCanonical "GPUCache"
      !insertmacro BfSafeDeleteElectron "DawnGraphiteCache"
      !insertmacro BfSafeDeleteCanonical "DawnGraphiteCache"
      !insertmacro BfSafeDeleteElectron "DawnWebGPUCache"
      !insertmacro BfSafeDeleteCanonical "DawnWebGPUCache"
      !insertmacro BfSafeDeleteElectron "Shared Dictionary"
      !insertmacro BfSafeDeleteCanonical "Shared Dictionary"
      !insertmacro BfSafeDeleteElectron "Preferences"
      !insertmacro BfSafeDeleteCanonical "Preferences"
      !insertmacro BfSafeDeleteElectron "Local State"
      !insertmacro BfSafeDeleteCanonical "Local State"
      !insertmacro BfSafeDeleteElectron "DIPS"
      !insertmacro BfSafeDeleteCanonical "DIPS"
      !insertmacro BfSafeDeleteElectron "DIPS-wal"
      !insertmacro BfSafeDeleteCanonical "DIPS-wal"
      !insertmacro BfSafeDeleteElectron "DIPS-shm"
      !insertmacro BfSafeDeleteCanonical "DIPS-shm"
      !insertmacro BfSafeDeleteElectron "DIPS-journal"
      !insertmacro BfSafeDeleteCanonical "DIPS-journal"
      !insertmacro BfSafeDeleteElectron "InterestGroups"
      !insertmacro BfSafeDeleteCanonical "InterestGroups"
      !insertmacro BfSafeDeleteElectron "InterestGroups-wal"
      !insertmacro BfSafeDeleteCanonical "InterestGroups-wal"
      !insertmacro BfSafeDeleteElectron "InterestGroups-shm"
      !insertmacro BfSafeDeleteCanonical "InterestGroups-shm"
      !insertmacro BfSafeDeleteElectron "InterestGroups-journal"
      !insertmacro BfSafeDeleteCanonical "InterestGroups-journal"
      !insertmacro BfSafeDeleteElectron "PrivateAggregation"
      !insertmacro BfSafeDeleteCanonical "PrivateAggregation"
      !insertmacro BfSafeDeleteElectron "PrivateAggregation-wal"
      !insertmacro BfSafeDeleteCanonical "PrivateAggregation-wal"
      !insertmacro BfSafeDeleteElectron "PrivateAggregation-shm"
      !insertmacro BfSafeDeleteCanonical "PrivateAggregation-shm"
      !insertmacro BfSafeDeleteElectron "PrivateAggregation-journal"
      !insertmacro BfSafeDeleteCanonical "PrivateAggregation-journal"
      !insertmacro BfSafeDeleteElectron "lockfile"
      !insertmacro BfSafeDeleteCanonical "lockfile"
      !insertmacro BfSafeDeleteElectron "DevToolsActivePort"
      !insertmacro BfSafeDeleteCanonical "DevToolsActivePort"
      !insertmacro BfSafeDeleteElectron ".factory-reset-pending"
      !insertmacro BfSafeDeleteCanonical ".factory-reset-pending"
    ${EndIf}

    ; Remove the canonical root only if every remaining entry was selected and
    ; safely removed. Unknown files keep the directory alive by design.
    RMDir "$APPDATA\BetterFingers"
    ; Electron's own folder, on the same terms: unknown files keep it alive.
    RMDir "$APPDATA\betterfingers-electron"
  ${EndIf}
!macroend

!endif
