**A legends viewer like no other!**
### Hello! 
Dwarfipedia is a suite of tools designed to expand your Dwarf Fortress worlds in a way that I've found to be much better suited for invoking imagination and curiosity. It does this by giving every individual thing in your world a Wikipedia-style page of information. Much of this information ==is not 1:1 faithful== to what the game simulated or what it can simulate naturally. Most of it is made up. There is of course, plenty of real data, which I will cover below, but the text content of a given page is all but certain to be factually incorrect. Why do I feel this is an acceptable compromise? Well, because I've always been fascinated by the stories that this game could give to you, but I've always felt that other legends viewer software stopped a bit short of actually stimulating the imagination. It is personally hard for me to visualize a person, or a site, by looking at a table of who stole what, and who fought whom. It has proven to be much easier for me to visualize something through an easy-to-digest, if fictional, account of it. The benefits of this approach are twofold: first, it makes the history of a world considerably easier to understand and visualize. Rather than asking you to reconstruct a person or place from a collection of disconnected events, Dwarfipedia presents that information in a form that can be read and understood naturally. Second, it gives the history room to inspire the imagination. Dwarf Fortress already provides an enormous amount of factual information about the people, places, and events in a world, but there is often very little connective tissue between those facts. Dwarfipedia attempts to fill that gap, turning the raw history of a world into something that feels like a collection of stories rather than a database of records.

![[dw1.png]]

### How does it work? 
For the main feature of this software, the wiki pages themselves, word and phrase banks are used to populate predetermined sections of a thing. In the screenshot example above, we've got a dwarf. The information contained in the vital record is always true to the game, but the text in the center is always going to be made up. As you can see, as with any random generation, the text can be a bit clunky at first. There are three different ways we can go about fixing this. The first, is to manually edit. If you like to write, like I do, you'll find that any page and any section can be edited on a whim. The second method, is to reroll the wordbank text. This can be done by clicking the 'Tools' button on any section header, same place you'd find the option to manually write. This would regenerate, and replace with more random strings. I've found it helpful to do this several times for each section until I've got stuff that is vaguely story shaped, and then write the stuff I personally want to expand, and use method 3 for the other stuff. Now, method 3 is entirely optional, and is not a requirement to install or use this software. Method 3 of fleshing out a page, is to use a local LLM. I've provided the software with sensible defaults for the prompts that the LLM will use, and it always pulls data from the page as its ultimate authority on context, meaning, it should write about that person or thing specifically, based on the other stuff you've written or generated about them or it. 

### What's included? 
 - Atlas: A home page to view and easily import your worlds that the software handles
 - Home Page: Inspired by news sites, a page that pulls random events from your world to help you find a rabbit hole to dive into
 - The Wiki itself: Covering Figures, Sites, Civilizations, Artifacts, Written works, and a bestiary
 - Written works have a small hidden feature unique to them: a "Book Reader" system. Wherein you can paste the contents of the book you're reading about, if you write it, or have an LLM write it for you, page by page. Once complete, you can click through the pages of your book. 
 - Cartography: Two different kinds of maps
	 - Region Map: An in-depth, interactive look at one specific world of yours
	 - Continent map: Inspired by the "Map Wall" that is possible in Minecraft, this is where you can stitch your regions together to create one continuous landmass, or a world. Editing tools let you smooth out the rough edges around borders
- Adventurer Guide: An interactive character sheet for playing adventure mode with. It can track your inventory, your quests, and more. This is manual though, unlike the next tool. 
- Fortress Guide: A tool that, upon a simple setup, can hook into DFHack and pull live data from a running instance of Dwarf Fortress in Fortress mode. A dashboard, more or less. 
- Dice and Calculator: I liked having these tools handy, so I put them in the software. 
- Calendar: This is experimental, and not quite working as I want it to, but it does a little bit, so I'm releasing it. It puts events that happened on the dwarven calendar for you to peruse. Another rabbit hole finding aid. 
- Timeline: Currently rudimentary, but being expanded, it's a long list of everything that happened in chronological order
- World Stats: Various helpful stats and graphs to quickly visualize the kinds of things in your world
- Bookmarks/Tags: Keep track of everything you find notable with a bookmark, organize large sets of similar things with tags. 
- Themes: Accessible in the settings dropdown, you can enjoy a wide selection of DF inspired color schemes, as well as High Contrast Light/Dark for easier reading
- Updating: A helpful tool to provide more recent legends data exports, as well as a queue to handle anything that might overwrite your edited pages, this queue can be manually tended to, so that your hard work is never just erased. ==Important: Make sure the world you are updating is selected in the world picking drop down next to search, or else you'll have a duplicate world on your hands!==
- Images/Gallery: Each page in the Wiki supports adding photos. This can be done with the optional image generation, or by manually selecting photos to add to a page. 

### System Requirements
Dwarfipedia was developed and tested on **Windows 11**. I do not currently have access to Linux or macOS systems for testing, so support for those platforms is experimental. Versions for those systems are provided, but I cannot guarantee that everything will work as intended. If you are running Linux or macOS and encounter an issue, please report it so I can investigate.

#### Dwarf Fortress Compatibility 
Dwarfipedia was developed for **Dwarf Fortress v0.53.16**.

I am an avid Dwarf Fortress player and intend to keep the software maintained alongside the game. If a new Dwarf Fortress patch breaks something, I will do my best to provide a fix as soon as possible.

**DFHack is Required** for two things:
1. Dwarfipedia relies on DFHack to export your world's Legends data in a format it can properly parse. DFHack can be uninstalled after the export if you prefer to play without it.
2. Fortress Guide: The Fortress Guide uses DFHack to retrieve live information from a running fortress. Dwarfipedia includes a guided setup process for installing the necessary script into your DFHack installation.

**Python 3.9** is also required. Other Python dependencies, including LXML and Flask, are installed automatically.
#### AI Features 
AI is **completely optional**. Dwarfipedia does not require an AI model or an internet connection to use its core features.

If you want to use the AI-assisted writing features, see **AI Features** below for additional installation instructions.

If you would prefer not to have the **Rewrite with AI** buttons present in the interface, feel free to open an issue and let me know. If there is enough demand, I may provide an AI-free version of the interface.

#### System Performance
Dwarfipedia was developed on a relatively powerful PC, but its resource usage has generally been fairly low during normal use.

Performance may vary considerably depending on the size of your world and which features you are using. If you encounter unexpectedly high CPU, memory, or disk usage, please open an issue with your system specifications and what you were doing when the problem occurred. I'll investigate it.

### Getting Started

Step 1: Download this repo as a zip
Step 2: Extract where you'd like this to live
Step 3: Open the folder, and run `dwarfwiki.bat`
Step 3a: If you are on Linux, run `./run.sh`
![[Pasted image 20260821171050.png]]

Step 4: The software will open in your default web browser, you'll be given this screen. 
Step 5: Inside of Dwarf Fortress, with DFHack installed, load/generate a world, and export its legends data by using the Export XML button. 
Step 6: Once complete, browse to your game files, and find the newly minted xml files. I move these to their own folder, but you don't have to. 
(If you are using Steam, and installed the game in a standard fashion, your legends files are going to be in: C:\Program Files (x86)\Steam\steamapps\common\Dwarf Fortress)

Step 7: Back in Dwarfipedia, click the relevant buttons to upload your legends.xml and your legends_plus.xml files into the software. Also, give the world a name. 
Step 8: Click Import, wait a few moments, and you're done!
![[Pasted image 20260821171541.png|700]]

Upon successful import, you'll be taken to the home page for your newly imported world. From here, the sky is the limit!
![[Pasted image 20260821171608.png]]

### Configuration
#### General Settings: 
There is still work to be done to improve the ease in which configuration can happen. At present, most of what the average person would want to change is done through the settings button in the navigation bar. Here, you can access themes, disable sound effects, toggle displaying images for printing, edit the LLM prompts, edit image generation settings, and download a backup of your world data. If there are settings you'd like to tweak, but find that you can't, please raise an issue and I'll investigate. 

#### Wordbank Text
If you wish to change the phrases used to generate pages, you can do that by navigating to `df\server\data`. In this folder, you will find 3 files. 
- `bestiary_wordbanks.json`
- `entity_wordbanks.json`
- `hf_wordbanks.json`

These files are what Dwarfipedia use to mash together the initial page text. In these files, you will find a vast assortment of phrases. You can write your own, delete the ones you don't like, or any combination of those things. Save your changes, and the software will adjust automatically going forward. This does not automatically retroactively change text, you'll have to reroll a page you've already visited to get the new changes. 

What are these files? Mostly, they are described in the file name. Bestiary covers the beasts of the world, and is the one most in need of a tune up in a later release. Entity covers things from towns to artifacts. hf_wordbanks covers all of the breathing people. 
#### LLM Settings
Because AI Generated text is a matter of personal preference, you may wish to tweak how the software sounds when using the LLM features. This can be done by accessing the `Edit AI Prompts` button in settings. On this screen, you'll see several sections. 

##### Style Seeds
Sentences written in these fields will steer how the LLM approaches the task of writing. You can adjust how many seeds are used on any given attempt, but I recommend a range between 8-12, as too many seeds will produce jumbled text. 

##### Banned Phrases
We've all seen the familiar LLM writing patterns. _"It's not X, it's Y."_ _"More than just..."_ and the other little linguistic fingerprints that seem to follow AI-generated prose everywhere. If you notice a particular phrase or writing pattern that your LLM keeps using and you'd rather it didn't, add it to this list. Dwarfipedia will instruct the model to avoid those phrases when generating text. This is particularly useful for gradually fine-tuning the writing style to your personal preferences.

##### Biography Prompt
The meat and potatoes. This is the one thing you're going to see the biggest personalization benefit by tuning to your preferences. By stating clearly what you want, what you don't want, the prompt in this field can be tuned to your exact desires. You can change whatever you don't like about the default prompt, or write your own entirely. 

![[Pasted image 20260821173600.png]]
##### Encyclopedia Prompt
For all other things that aren't breathing entities. I separated the two, because during testing I found that I preferred a castle to be written about differently than I wanted a person to be written about. If this is not the case for you, simply copying the biography prompt should fix that. Much the same as above, you can tweak the default or write your own for how you wish things to be written. 

##### Commerce Prompt
Used in the trade section of settlements. Again, I split this, as giving the LLM specific instructions on how to write about trade/markets felt better when it was separate from how it writes about castles. All the same rules of the other two prompt fields apply here. 

==**Tip:** You don't need to get these prompts perfect on your first attempt. Experiment with them. If you don't like the results, change a few instructions and try again. ==

### AI Features
There are two types of AI implemented for optional use in this software. The first, and most important, is a local LLM. I designed this software to use Ollama. Why Ollama? Because it requires no API access, no rate limiting, and no accounts. Nothing gets sent over the internet. This is the most ethical implementation of an LLM I can think of. 

##### The LLM (Writing)
Download at: [Download Ollama on Windows](https://ollama.com/download/windows)
or by opening Powershell, and running: `irm https://ollama.com/install.ps1 | iex`
Once installed, proceed to the step below. 

**Model recommendation**: Default is `llama3.1:8b` (pulled with `ollama pull llama3.1:8b`). It's configurable via an environment variable (`DWARFWIKI_MODEL`) if you want to use a different one, e.g.  `llama3.2:3b` is smaller and is suggested as a for slower machines.

**Connecting it to Dwarfipedia**: There's no setup screen for this; it's automatic. Dwarfipedia just checks `http://localhost:11434` (Ollama's default port) before each request. If Ollama's running, generation works; if not, the button fails with an error. The address is overridable via `DWARFWIKI_OLLAMA` if Ollama runs elsewhere.

**What happens when you press "Rewrite with AI"**?: Dwarfipedia gathers real facts about that specific entity (see below), builds a prompt combining those facts + the section's current text + a system prompt, sends it to Ollama, and replaces that one section with the response. Nothing else on the page changes, and the old text isn't lost. Every section keeps a small tag showing whether it's original ("wordbank"), hand-edited, or LLM-written, and it can be reset back.

**How factual page data is supplied to the model**: For a person: name, race, sex, birth/death year, associated "spheres," top skills, and known relationships (to other named figures), plus a trimmed excerpt of the entity's _other_ existing sections (so new text stays consistent with what's already on the page). For a creature: race, population/event counts, and named specimens. Raw event lists are deliberately left out, these are too bulky and low-value for an 8B model. The model is explicitly instructed not to invent new hard facts (names, dates, deaths, relationships), only atmosphere and prose style. This can of course, be edited through the settings, if you'd like. 

##### The Image Generation
The second AI feature is local image generation. I designed this to talk to a local Stable Diffusion WebUI Install, specifically Forge. This was done with the same reasoning as Ollama, no accounts or API keys, and no usage limits. Again, this is entirely optional, and the software supports manually uploading image files without generating them, for the artistically inclined user. 

**Installing Forge**: Download here: [lllyasviel/stable-diffusion-webui-forge](https://github.com/lllyasviel/stable-diffusion-webui-forge)
==Grab the "One-Click Install Package"==. Extract it somewhere, and then run `update.bat`. Once done, run `run.bat`. 

The first launch will download a couple GBs worth of dependencies. Once this is done, it will open a browser tab at: http://127.0.0.1:7860. 

You'll also need at least one model file ("checkpoint," .safetensors) dropped into Forge's models/Stable-diffusion/ folder. Forge is just the engine, the checkpoint is what creates the images, and there isn't one bundled.

Finally, Forge's API is off by default. Open `webui-user.bat`, find the `set COMMANDLINE_ARGS=` line, and add `--api` to it. This is the step people miss without it, Forge runs fine but Dwarfipedia can't reach it.

**Connecting it to Dwarfipedia**: Same as Ollama, Dwarfipedia checks `http://127.0.0.1:7860` (Forge's default port) before each request. Settings → Image style shows live connection status ("Image server connected," with your model listed, or "No image server found" with guidance). The address is overridable via `DWARFWIKI_SD` if Forge runs elsewhere.

==Since both of these tools can be a drain on resources, I often keep them closed, (Ollama needs closed through the system tray) until I wish to use them. Each time you wish to use the image generation, you will need to run `run.bat` but you can close everything except for the console window.==

**How style/config is supplied**: Settings → Image style holds an editable positive style prompt (what's asked for on every drawing), a negative prompt (what to steer away from), and a pool of style-seed variations drawn a couple at a time per image so repeated drawings of the same person don't look identical, same idea as the text style seeds. All fully editable and resettable, same as the LLM prompts.

### Known Issues/Limitations
- Calendar tool is experimental
- Timeline is currently very basic
- Linux/macOS aren't tested
- Wordbank text can be improved in later iterations
- LLM quality depends on the model, working on packaging a lightweight LLM specifically for DF writing, but that's months out
- Updating may break certain features, but hopefully not the main workflow of "Import world, read world, map world". 

### Roadmap
- As mentioned above, I would love to package a lightweight LLM that requires no end user setup, and can be lightweight enough to run on low-mid range hardware. Limitations are just suggested starting points for innovation. 
- Of course, fix the basic features, such as the timeline and the calendar. 
- Potentially introduce a live refresh to Adventure Guide, Similar to Fortress Guide, so that you can easily populate your journal/quest log with real game data
- Improve the generated prose so the default output requires less manual cleanup.
- Improve error handling and give users clearer explanations when something fails.
- More detailed biographies: Expand figures beyond the current predetermined sections.
- Family trees: Let users visually explore relationships between historical figures.
- Search support for things like “all dwarves who fought in X,” “artifacts stolen by Y,” or “settlements destroyed before year 100.”
- More specialized prompts for battles, artifacts, civilizations, sites, etc.
- AI-assisted summaries/Proc-Gen Summaries for non AI users
- Generate book contents for the Book Reader.
- Linux/macOS testing and support
- Better installation/update process
- Documentation improvements
- Community contributions / custom wordbanks
- Localization

### Troubleshooting/FAQ 
At the time of this initial upload, I don't quite know what is broken. Everything runs fine on my machine, but I understand that saying this is like invoking a curse. When/if you encounter difficulty, please open an issue through this GitHub page, I will be quite delighted that people like to use my software, and will provide technical support where I can, bugfixes where appropriate, and therapy resources, should the situation be deemed dire enough. In the future, this section will be more helpful as I get an understanding of some common troubles and questions. 

### Contributing
Dwarfipedia is a personal project, but contributions are welcome! There are plenty of ways to help, and you don't need to be a programmer to contribute. 

**Bug Reporting**: If you encounter an error, please open an issue on GitHub. When reporting a bug, please include as much of the following information as you can: 
- What were you trying to do when the problem occurred? 
- What did you expect to happen? 
- Any error messages? 
- Your Operating System
- DF Version
- Steps to reproduce the problem, if possible
A screenshot is often helpful. 

**Feature Requests**: If you have an idea for how to make Dwarfipedia the best tool for fans of Dwarf Fortress, please share it! Open an issue describing what you'd like to see, and why you think it would be useful. Ideas that fit into Dwarfipedia's goal of making DF history easier to understand and more interesting to explore are especially welcome. 

**Wordbanks**: One of the easiest ways to contribute is to improve Dwarfipedia's wordbanks. If you have ideas for better phrases, descriptions, writing styles, or ways of describing things, feel free to submit them. I would love to see this project become community supported by way of wordbank packs that can be easily dropped in, similar to texture packs in Minecraft. 

**Code Contributions**: I am a novice, so therefore pull requests are welcome for bug fixes, improvements, and new features. If you're planning a larger change, please open an issue first so the idea can be discussed. 

**Testing**: Dwarfipedia was developed and tested on Windows 11. By using the software on other operating systems, using different hardware, and reporting any issues or difficulties, you can help make this software more accessible to more people!

### Credits & Acknowledgements

Dwarfipedia would not exist without the work of the people and projects below.
#### Dwarf Fortress
A huge thank you to **Tarn Adams** and **Zach Adams** for creating Dwarf Fortress and continuing to develop one of the most fascinating games I've ever played. Dwarfipedia exists because Dwarf Fortress generates worlds worth getting lost in. Without the ridiculous amount of history, characters, places, artifacts, and stories that the game produces, there would be nothing for this project to explore.
#### DFHack
Thank you to the **DFHack team** for providing the tools that make it possible for Dwarfipedia to interact with Dwarf Fortress and access its Legends data. DFHack is used for the Legends export process and powers the live connection used by Fortress Guide.
#### Kenney
Thank you to **Kenney** for providing high-quality, freely available game-development assets and sound effects through [Kenney.nl](https://kenney.nl/). The sound effects used throughout Dwarfipedia were sourced from Kenney's public asset library.

#### Open Source Software
Dwarfipedia also makes use of a number of open-source libraries and projects.

- [**Flask**](https://flask.palletsprojects.com/) — The web framework used to serve Dwarfipedia's local web interface. Flask is distributed under the BSD 3-Clause License.
- [**lxml**](https://lxml.de/) — Used for parsing and processing the XML data produced by Dwarf Fortress. lxml is distributed under the BSD license, with additional licensing applicable to some bundled components.

A special thank you to everyone who makes open-source software and freely available creative assets possible. Dwarfipedia stands on a rather large pile of other people's excellent work.

### License
Dwarfipedia is released under the **GNU General Public License v3.0 (GPLv3)**.
You are free to use, study, modify, and redistribute Dwarfipedia. You may use it for personal or commercial purposes, and you are free to create and distribute your own modified versions.

The GPLv3 is a copyleft license, meaning that distributed modified versions of Dwarfipedia must remain available under the same license and include the corresponding source code.
In short: **use it, change it, build on it, share it. Just keep it free and open for the next person, too.**
See the LICENSE file for the complete license text and terms.

#### Copyright
Dwarfipedia is an independent, unofficial project and is not affiliated with or endorsed by Bay 12 Games or the creators of Dwarf Fortress.
Dwarf Fortress is the property of Bay 12 Games. You can find more information about Dwarf Fortress by visiting: [Bay 12 Games: Dwarf Fortress](https://bay12games.com/dwarves/)
### Disclaimer
Dwarfipedia is an **unofficial, fan-made project** and is not affiliated with, endorsed by, or sponsored by **Bay 12 Games**, Tarn Adams, or Zach Adams.
**Dwarf Fortress** and all associated trademarks, game assets, and intellectual property remain the property of their respective owners. Dwarfipedia does not include or redistribute the Dwarf Fortress game itself.

Dwarfipedia is designed to read and interpret Legends data exported from Dwarf Fortress. The factual information displayed by Dwarfipedia is derived from that exported data, but the narrative text generated by its wordbanks and optional LLM features is **fictional and interpretive**. It should not be treated as an accurate representation of what Dwarf Fortress actually simulated.

Dwarfipedia makes no guarantee that generated text will be accurate, sensible, grammatically correct, or consistent with the game's underlying history. It is intended as a tool for exploration, interpretation, and imagination. Use Dwarfipedia at your own discretion, and keep backups of any important world data or writing.
