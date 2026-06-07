from kokoro_sound_engineer import KokoroSoundEngineer

engineer = KokoroSoundEngineer(project_name="test_proj")
engineer.load_project_memory({
    "Cabbaro Pulse": "[Cabbaro Pulse](/kæbˈɑɹoʊ pˈʌls/)"
})

text = "Rodney looked at him and said he was sorry but Louie knew he wasn't... The rain kept hitting the dock, like coins thrown by a cheap god. Cabbaro Pulse."
chunks = engineer.prepare_text(text)

for c in chunks:
    print(c)
