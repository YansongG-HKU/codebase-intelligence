import { helper } from "./helpers";
import { Point } from "./types";

export interface Point {
    x: number;
    y: number;
}

export enum Color { Red = 0 }

export type Id = string;

export class Service implements Runnable {
    run(): void {
        helper();
    }
}
