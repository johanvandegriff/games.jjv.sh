package main

import (
	"bytes"
	"fmt"
	"html/template"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/gorilla/mux"
)

var (
	headRegex  = regexp.MustCompile(`(?is)<head[^>]*>(.*?)</head>`)
	bodyRegex  = regexp.MustCompile(`(?is)<body[^>]*>(.*?)</body>`)
	titleRegex = regexp.MustCompile(`(?is)<title>(.*?)</title>`)

	indexTemplate  = loadTemplate("templates/index.html", "templates/head.html", "templates/header.html", "templates/footer.html")
	headTemplate   = loadTemplate("templates/head.html")
	headerTemplate = loadTemplate("templates/header.html")
	footerTemplate = loadTemplate("templates/footer.html")

	titlePrefix = "games.jjv.sh | "

	nav = []NavItem{
		//Name    URLs
		{"home", []string{"https://jjv.sh"}},
		{"games", []string{"/"}},
		{"boggle", []string{"/boggle"}},
		{"CARL", []string{"/carl"}},
		{"chem", []string{"/chem"}},
		{"Dr. H", []string{"/hornswiggle"}},
		{"maze", []string{"/maze"}},
		{"maze.pl", []string{"/pl/maze.pl", "/pl/showmaze.pl"}},
		{"math.pl", []string{"/pl/math.pl", "/pl/math_score.pl"}},
		{"whack.pl", []string{"/pl/whack.pl"}},
	}

	apps = map[string]string{
		//URL          host & port
		"boggle":      getEnvDefault("BOGGLE_URL", "http://localhost:8081"),
		"boggle-old":  getEnvDefault("BOGGLE_OLD_URL", "http://localhost:8082"),
		"carl":        getEnvDefault("CARL_URL", "http://localhost:8083"),
		"chem":        getEnvDefault("CHEM_URL", "http://localhost:8084"),
		"hornswiggle": getEnvDefault("HORNSWIGGLE_URL", "http://localhost:8085"),
		"maze":        getEnvDefault("MAZE_URL", "http://localhost:8086"),
		"pl":          getEnvDefault("PERL_GAMES_URL", "http://localhost:8087"),
	}
)

type NavItem struct {
	Name string
	URLs []string
}

func getEnvDefault(key string, defaultValue string) string {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}
	return value
}

func tmplData(active string) map[string]any {
	return map[string]any{
		"active":       active,
		"nav":          nav,
		"navItemWidth": 100.0 / len(nav),
	}
}

func loadTemplate(filenames ...string) *template.Template {
	return template.Must(template.ParseFiles(filenames...))
}

func renderTemplate(tmpl *template.Template, data map[string]any) string {
	var buffer bytes.Buffer
	if err := tmpl.Execute(&buffer, data); err != nil {
		s := fmt.Sprintf("Error executing template: %v", err)
		log.Println(s)
		return s
	}

	return buffer.String()
}

// indexHandler -> GET /
func indexHandler(w http.ResponseWriter, r *http.Request) {
	indexTemplate.Execute(w, tmplData("games"))
}

// Modify the head content to append a prefix to <title>, or insert a new title
func modifyTitle(headContent string, active string) string {
	titleMatch := titleRegex.FindStringSubmatch(headContent)

	if len(titleMatch) > 1 {
		// Modify existing title
		modifiedTitle := "<title>" + titlePrefix + titleMatch[1] + "</title>"
		headContent = titleRegex.ReplaceAllString(headContent, modifiedTitle)
	} else {
		// No existing title, insert one using the Page variable
		newTitle := "<title>" + titlePrefix + active + "</title>"
		headContent = headContent + "\n" + newTitle
	}

	return headContent
}

func modifyHTMLResponse(originalHTML string, active string) string {
	var headContent, bodyContent string

	// Extract <head> content
	headMatches := headRegex.FindStringSubmatch(originalHTML)
	if len(headMatches) > 1 {
		headContent = headMatches[1]
	} else {
		headContent = "" // No head found, assume empty
	}

	// Extract <body> content
	bodyMatches := bodyRegex.FindStringSubmatch(originalHTML)
	if len(bodyMatches) > 1 {
		bodyContent = bodyMatches[1]
	} else {
		// No body tag found, assume entire content is the body
		bodyContent = originalHTML
	}

	// Modify the <head> content to update the <title>
	headContent = modifyTitle(headContent, active)

	data := tmplData(active)
	extraHeadContent := renderTemplate(headTemplate, data)
	headerContent := renderTemplate(headerTemplate, data)
	footerContent := renderTemplate(footerTemplate, data)

	// Assemble the new HTML
	modifiedHTML := "<!DOCTYPE html>\n<html>\n<head>\n" +
		extraHeadContent + headContent + "\n</head>\n<body>\n" +
		headerContent + bodyContent + footerContent +
		"\n</body>\n</html>"

	return modifiedHTML
}

func main() {
	router := mux.NewRouter()
	router.HandleFunc("/", indexHandler)
	router.HandleFunc("/favicon.ico", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "favicon.ico")
	})

	// Tell the router to use that file server for all /static/* paths
	router.PathPrefix("/static/").Handler(http.StripPrefix("/static/", http.FileServer(http.Dir("./static"))))

	router.PathPrefix("/{app}").HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		appName := mux.Vars(req)["app"]
		targetHost := apps[appName]

		parsedURL, err := url.Parse(targetHost)
		if err != nil {
			log.Printf("error parsing target host: %v", err)
			http.NotFound(w, req)
			return
		}

		proxy := httputil.NewSingleHostReverseProxy(parsedURL)

		// Customize the proxy response handler
		proxy.ModifyResponse = func(resp *http.Response) error {
			contentType := resp.Header.Get("Content-Type")
			if !strings.HasPrefix(contentType, "text/html") {
				return nil // Do not modify non-HTML responses
			}

			// Modify response headers
			// resp.Header.Set("X-Custom-Header", "ModifiedByProxy")

			// Read and modify response body
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}

			r := regexp.MustCompile(`^(http[s]?:)+\/\/([^:\/\s]+)(:[0-9]+)?([^#?\s]+)(\?[^#]*)?(#.*)?$`)
			fmt.Println(resp.Request.URL, r.FindStringSubmatch(resp.Request.URL.String()))
			matches := r.FindStringSubmatch(resp.Request.URL.String())
			active := ""
			if len(matches) > 4 {
				path := matches[4]
				for _, navItem := range nav {
					for _, URL := range navItem.URLs {
						if strings.HasPrefix(path, URL) {
							active = navItem.Name
						}
					}
				}
			}

			// Modify HTML content
			modifiedBody := []byte(modifyHTMLResponse(string(body), active))

			// Replace the response body
			resp.Body = io.NopCloser(bytes.NewReader(modifiedBody))
			resp.ContentLength = int64(len(modifiedBody))
			resp.Header.Set("Content-Length", fmt.Sprint(len(modifiedBody)))

			return nil
		}

		// Set a custom transport with a short dial timeout.
		proxy.Transport = &http.Transport{
			DialContext: (&net.Dialer{
				Timeout:   2 * time.Second, // adjust timeout as needed
				KeepAlive: 30 * time.Second,
			}).DialContext,
			TLSHandshakeTimeout: 2 * time.Second,
		}

		proxy.ErrorHandler = func(rw http.ResponseWriter, r *http.Request, e error) {
			log.Printf("404 for app: %s proxy error: %v", targetHost, e)
			html := `<h1>404 - App Not Found</h1>
<p>The requested URL was not found on this server.</p>
<p><a href="/">back to homepage</a></p>`
			rw.WriteHeader(http.StatusNotFound)
			rw.Header().Set("Content-Type", "text/html; charset=utf-8")
			_, _ = rw.Write([]byte(html))
		}

		proxy.ServeHTTP(w, req)
	})

	PORT := getEnvDefault("PORT", "8080")
	srv := &http.Server{
		Handler: router,
		Addr:    ":" + PORT,
	}

	log.Printf("listening on port %s", PORT)
	log.Fatal(srv.ListenAndServe())
}
