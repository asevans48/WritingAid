## Writer Platform

You are a developer building a software platform for writers that helps organize


The writer platform allows writers to organize 


## Technologies

- Python
- PyQT6
- LLMs such as claude, gemini, chatgpt, and sora
- Additional dependencies


## Hierarcy

- Project: the root level encapsulating all work including the manuscripts
    -  Features: listed below, encapsulate the work

## Features

The project allows users to open and save all content per project.

The following are requirements for the application. These can be split into several sections which are distinct. The parts are: 
    - worldbuilding: section with subsections for mythology, planets, climate, history, politics, military, economy, and the power hierarchy.
    - characters: section for antagonists, protagonists, major, and minor characters where users can upload a character image, develop personalities, create backstores, map character's social networks, and more.
    - story planning: section that allows users to build a freytag pyramid, describe their plot, describe subplots and connect them to the main plot
    - manuscript generation: section where users can upload word documents and prepare a manuscript to publishable standards for kindle, barnes and noble, and other presses (please research this). users can also write chapters in the tool with font and other aids. An LLM should offer hints at the click of a button for a chapter. Our unit is a chapter but we wish to have the LLM offer hints relevant to the entire manuscript and help users jump between chapters as they write. A revision system should be included at the chapter level capable of handling large chapters. INCLUDE exporters for kindle, barnes and noble, and publisher ready manuscripts and works.
    - image and coverart generator: section where users can generate coverart, images, character profile shots that save to the character section, help writers turn sections into art to get a feel for what they are creating
    - grader: this section should offer a brutal critique of chapters and manuscripts, offer line-item edits, and allow users to discover what needs to be done to make the 
    - Agent Management: allow users to create and send emails around manuscripts. this may be embellished later. Allow users to publish to Kindle if possible and other platforms in their formats.

Characters and world components are seen as objects that can be connected via story planning. All tasks can be worked with the help of an Agentic suite using a configurable AI. We prefer to see if claude via an anthropic subscription is usable and offer claude API, chatGPT API, and gemini API key configuration.


## AI

We want AI to serve as a guide. We should offer a chat capability that persists as well as a langgraph and langchain agentic system that calls LLMS to help with editing, worldbuilding, story planning, image generation, and more.

Allow users to chat via a persistant, collapsable chatbox. 

The AI should offer honest and brutal feedback and criticism. It should offer recommendation where possible.

### Prompting

Prompts should be thorough and help create compelling works of art. DO NOT allow LLMS to train off the data sent.


## Managing Dependencies

Place all dependencies in a requirements.txt file.


## Additional Capabilities

If you can think of anything else to add, please do.


## Manuscript Editor

Model the manuscript editor off of word with AI and chapter skipping. Remember that the core unit is a chapter. Users should be able to navigate to chapters

### Spelling and grammar

If there is a deterministic tool that can be used for spelling and grammar checking in the manuscript generation. Please add it.

## Dictionary

Creat a generic dictionary per project.


## Writing Rules

For writing rules, make sure any prompt ensures that:

- We are mostly showing over telling
- Creating compelling and emotional stories
- Not violating plot points
- ONLY uses natural transitions
- Detects and helps eliminate tropes to create something unique
- Ensures that writing is readable, compelling, and that sentences have variety and uniqueness


## UI Rules

The UI should work on a variety of screens from small laptops to large screens. Make the UI user friendly. DO NOT mash buttons together. DO NOT use sizes for buttons that cause things to run together. USE scroll bars where applicable.