// Fixture: declarations, relative imports, ambiguity and external import.
import React from "react";
import "./helpers";
import "./dupe";
import "./nope";

export class Widget extends Base {
    render() {
        return helper();
    }
}

export function build() {
    const widget = new Widget();
    return widget.render();
}

const MAX_SIZE = 10;
