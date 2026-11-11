package catalog;

import java.util.ArrayList;
import java.util.List;

/** Catalog exposes the symbols known to the dashboard. */
public class Catalog {
    private final List<String> symbols = new ArrayList<>();

    public void addSymbol(String symbol) {
        symbols.add(symbol);
    }

    public List<String> listSymbols() {
        return List.copyOf(symbols);
    }

    public int size() {
        return symbols.size();
    }
}
