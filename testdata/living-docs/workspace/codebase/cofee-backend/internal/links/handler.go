package links

type Handler struct{ svc *Service }

func (h *Handler) CreateLink(w ResponseWriter, r *Request) {}
func (h *Handler) Disable(w ResponseWriter, r *Request)    {}
func (h *Handler) Get(w ResponseWriter, r *Request)        {}
