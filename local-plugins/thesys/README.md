## Overview

This plugin adds a dedicated Thesys model provider for Dify.
It keeps the provider UX focused on Thesys instead of exposing the full generic
OpenAI-compatible surface.

## Configure

1. Install the plugin package in Dify.
2. Add your Thesys API key in the Model Provider page.
3. Use the predefined sample model or add a custom model with the exact Thesys model id.

The provider always targets the Thesys OpenAI-compatible embed endpoint:

`https://api.thesys.dev/v1/embed`
